from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import difflib
import hashlib
import json
import re
import unicodedata
from pathlib import Path

from novel_flywheel.db import Database
from novel_flywheel.model_output import canonical_model_label, parse_json_object
from novel_flywheel.projects import ProjectCreate, ProjectStore
from novel_flywheel.storage import atomic_write
from novel_flywheel.story_state import StoryStateStore, validate_locked_facts


MAX_OUTLINE_CHARACTERS = 100_000
MARKET_REFERENCE_MECHANISM_LIMIT = 5
_OUTLINE_QUESTION_SIGNAL = re.compile(r"[？?]|为什么|怎么会|究竟")
_OUTLINE_ANOMALY_SIGNAL = re.compile(r"突然|竟然?|却|失踪|死亡|异常|不见了|消失")
OUTLINE_EVENT_SKIP_TERMS = (
    "必须达成", "写作技法", "状态变化", "下一步选择", "全篇收束", "要素确认",
    "主要人物", "关键配角", "核心设定", "核心矛盾", "说明", "提示",
)
OUTLINE_EVENT_KINDS = {"narrative", "structure", "theme", "directive"}
OUTLINE_CHANGE_TYPE_ALIASES = {
    "changed": "changed", "change": "changed", "modified": "changed",
    "content_changed": "changed", "已修改": "changed", "内容变化": "changed",
    "reordered": "reordered", "reorder": "reordered", "moved": "reordered",
    "order_changed": "reordered", "顺序变化": "reordered", "已调序": "reordered",
    "uncertain": "uncertain", "unknown": "uncertain", "needs_review": "uncertain",
    "不确定": "uncertain", "需复核": "uncertain", "无法判断": "uncertain",
}
_OUTLINE_THEME_SECTIONS = {
    "主题", "主题设计", "主题与情感线", "情感线", "人物弧光", "角色弧光",
}
_OUTLINE_DIRECTIVE_SECTIONS = {
    "故事核心设定", "核心设定", "基础设定", "人物设定", "角色设定", "世界观设定",
    "写作要点", "写作要求", "创作要求", "创作说明", "文风要求", "风格要求",
    "备注", "附录",
}
_OUTLINE_STRUCTURE_SECTIONS = {
    "章节大纲", "章节规划", "章节安排", "分章大纲", "分章规划",
    "剧情结构", "故事结构", "剧情大纲", "故事大纲", "整体结构", "篇章结构",
}
_OUTLINE_SECTION_NUMBER = re.compile(
    r"^(?:\(\s*(?:[一二三四五六七八九十百零〇两]+|[0-9]+)\s*\)"
    r"|(?:[一二三四五六七八九十百零〇两]+|[0-9]+)\s*[)、.:：、])\s*"
)
_OUTLINE_CHAPTER_LABEL = re.compile(
    r"^(?:第[一二三四五六七八九十百零〇两0-9０-９]+章"
    r"|chapter\s*[0-9０-９ivx]+)(?P<suffix>.*)$",
    flags=re.IGNORECASE,
)
_OUTLINE_STRUCTURE_LABEL = re.compile(
    r"^(?:第[一二三四五六七八九十百零〇两0-9０-９]+(?:幕|卷|部|篇|阶段|单元|场)"
    r"|(?:act|part|volume|book|phase|arc|section|sequence|scene)"
    r"\s*[0-9０-９ivx]+)(?:\b|[·：:\s])",
    flags=re.IGNORECASE,
)


def _visible_outline_markdown(content: str) -> str:
    """Remove non-visible template syntax before semantic outline scans."""
    content = re.sub(r"<!--.*?-->", "", str(content or ""), flags=re.DOTALL)
    visible: list[str] = []
    fence_character = ""
    fence_length = 0
    for line in content.splitlines(keepends=True):
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


def compact_market_reference(baseline: dict | None) -> dict:
    """Keep only bounded, non-authoritative market facts used by outline tools."""
    if not isinstance(baseline, dict):
        return {
            "status": "unavailable", "sample_count": 0, "advisory_only": True,
            "message": "已启用同类市场参考，但还没有可用的本地基线。",
            "opening": {}, "mechanisms": [],
        }
    try:
        sample_count = max(0, int(baseline.get("sample_count") or 0))
    except (TypeError, ValueError):
        sample_count = 0
    status = "insufficient" if sample_count < 5 else "preliminary" if sample_count < 10 else "advisory"
    message = (
        f"只有 {sample_count} 篇已确认同类样本，数量不足，暂不据此判断大纲。"
        if status == "insufficient" else
        f"参考 {sample_count} 篇已确认同类样本，仅提供初步提示，不作为应用条件。"
        if status == "preliminary" else
        f"参考 {sample_count} 篇已确认同类样本，只供取舍，不代表质量结论。"
    )

    def percent(value) -> float:
        try:
            return round(max(0.0, min(100.0, float(value))), 1)
        except (TypeError, ValueError):
            return 0.0

    opening = baseline.get("opening") if isinstance(baseline.get("opening"), dict) else {}
    mechanisms = []
    for item in (baseline.get("mechanisms") or []) if status != "insufficient" else []:
        if not isinstance(item, dict) or not str(item.get("name") or "").strip():
            continue
        try:
            work_count = max(0, int(item.get("work_count") or 0))
        except (TypeError, ValueError):
            work_count = 0
        position = item.get("position_median")
        mechanisms.append({
            "name": str(item["name"]).strip()[:80],
            "work_count": min(work_count, sample_count),
            "position_median": percent(position) if position is not None else None,
        })
        if len(mechanisms) >= MARKET_REFERENCE_MECHANISM_LIMIT:
            break
    key = baseline.get("key") if isinstance(baseline.get("key"), dict) else {}
    return {
        "status": status,
        "sample_count": sample_count,
        "advisory_only": True,
        "message": message,
        "cohort": {
            field: str(key.get(field) or "")[:60]
            for field in ("platform", "ranking_name", "category", "length_type")
            if key.get(field)
        },
        "opening": {
            "question_percent": percent(opening.get("question_percent")),
            "anomaly_percent": percent(opening.get("anomaly_percent")),
        } if status != "insufficient" else {},
        "mechanisms": mechanisms,
        "boundary": str(baseline.get("boundary") or "仅描述本地已确认样本，不代表成功原因或质量标准。")[:240],
    }


CHARACTER_ROLE_LABELS = {
    "女主": "protagonist", "主角": "protagonist", "主人公": "protagonist",
    "男主": "counterpart", "男主人公": "counterpart",
    "反派": "antagonist", "对手": "antagonist",
    "配角": "supporting", "重要配角": "supporting", "关键配角": "supporting",
}
CHARACTER_GROUP_LABELS = {
    "人物", "人物设定", "人物介绍", "主要人物", "登场人物", "角色", "角色设定",
    "角色介绍", "重要配角", "关键配角", "配角",
}
CHARACTER_FIELD_LABELS = {
    *CHARACTER_GROUP_LABELS, *CHARACTER_ROLE_LABELS,
    "姓名", "名字", "年龄", "身份", "性格", "性情", "外貌", "背景", "经历", "动机",
    "目标", "欲望", "需求", "能力", "特点", "作用", "关系", "弧光", "结局", "设定",
}


def extract_outline_characters(content: str) -> list[dict[str, str]]:
    """Extract explicitly named cast members from common Chinese outline formats."""
    found: dict[str, dict[str, str]] = {}

    def role_for(value: str, default: str = "supporting") -> str:
        compact = re.sub(r"\s+", "", value)
        return next((role for label, role in CHARACTER_ROLE_LABELS.items()
                     if label in compact), default)

    def add(raw_name: str, role: str = "supporting") -> None:
        for value in re.split(r"[、，,；;/]", raw_name):
            name = value.strip().strip("*# `\"'“”‘’（）()【】[]")
            name = re.split(r"[：:（(【\[]", name, maxsplit=1)[0].strip()
            compact = re.sub(r"\s+", "", name)
            if (
                compact in CHARACTER_FIELD_LABELS
                or not re.fullmatch(
                    r"[\u3400-\u9fff·]{2,8}|[A-Za-z][A-Za-z .'-]{1,29}", name,
                )
            ):
                continue
            current = found.get(name)
            if current is None or current["role"] == "supporting" and role != "supporting":
                found[name] = {"name": name, "role": role}

    lines = _visible_outline_markdown(content).splitlines()
    in_character_section = False
    section_role = "supporting"
    for raw_line in lines:
        line = raw_line.strip()
        heading = re.match(r"^(#{2,6})\s+(.+?)\s*$", line)
        heading_text = heading.group(2).strip() if heading else ""
        if heading and len(heading.group(1)) == 2:
            compact = re.sub(r"[\s一二三四五六七八九十、.．]+", "", heading_text)
            in_character_section = any(label in compact for label in ("人物", "角色"))
            section_role = "supporting"

        source = heading_text if heading else re.sub(r"^[-*+]\s*", "", line)
        source = source.strip("*")
        role_then_name = re.match(
            r"^(女主|男主|主角|主人公|男主人公|反派|对手|重要配角|关键配角|配角)"
            r"\s*(?:[：:]\s*|[（(])(.+?)(?:[）)]\s*)?$",
            source,
        )
        if role_then_name:
            label, names = role_then_name.groups()
            add(names, CHARACTER_ROLE_LABELS[label])
            section_role = CHARACTER_ROLE_LABELS[label]
            continue

        name_then_role = re.match(
            r"^(.+?)\s*[（(](女主|男主|主角|主人公|男主人公|反派|对手|"
            r"重要配角|关键配角|配角)(?:[^）)]*)[）)]$",
            source,
        )
        if name_then_role:
            name, label = name_then_role.groups()
            add(name, CHARACTER_ROLE_LABELS[label])
            section_role = CHARACTER_ROLE_LABELS[label]
            continue

        compact_source = re.sub(r"\s+", "", source)
        if compact_source in CHARACTER_ROLE_LABELS:
            section_role = CHARACTER_ROLE_LABELS[compact_source]
            continue
        if compact_source in CHARACTER_GROUP_LABELS:
            section_role = "supporting"
            continue

        for name, descriptor in re.findall(r"\*\*([^*\n（）()：:]{2,30})[（(]([^）)]+)[）)]\*\*", line):
            if any(label in descriptor for label in CHARACTER_ROLE_LABELS):
                add(name, role_for(descriptor))
            elif any(label in descriptor for label in ("千金", "孤女", "姑娘", "丫头")):
                add(name, "protagonist")

        if not in_character_section:
            continue

        named_bullet = re.match(
            r"^(?:[-*+]\s*)?\*\*([^*\n]{2,30})\*\*\s*[：:]", line,
        )
        if named_bullet:
            add(named_bullet.group(1), section_role)
        if line.startswith("|") and line.endswith("|") and "---" not in line:
            cells = [cell.strip().strip("*") for cell in line.strip("|").split("|")]
            role_cell = next((cell for cell in cells if role_for(cell, "") != ""), "")
            if role_cell:
                role = role_for(role_cell)
                for cell in cells:
                    if cell != role_cell:
                        before = len(found)
                        add(cell, role)
                        if len(found) > before:
                            break
    return list(found.values())


OUTLINE_MANIFEST_KEYS = (
    "characters", "world", "locations", "plot_arcs", "timeline",
    "promises", "questions", "constraints",
)


def local_outline_manifest(content: str) -> dict[str, list[dict[str, str]]]:
    """Read explicit Markdown structure without treating ordinary prose as entities."""
    manifest = {key: [] for key in OUTLINE_MANIFEST_KEYS}
    lines = _visible_outline_markdown(content).splitlines()
    for character in extract_outline_characters(content):
        evidence = next((line.strip() for line in lines if character["name"] in line), "")
        if evidence:
            manifest["characters"].append({**character, "evidence": evidence})

    section = ""
    for raw_line in lines:
        line = raw_line.strip()
        heading = re.match(r"^(#{2,6})\s+(.+?)\s*$", line)
        if heading:
            level, label = len(heading.group(1)), heading.group(2).strip()
            if level == 2:
                section = label
            if level == 3 and re.search(r"幕|阶段|卷", label):
                manifest["plot_arcs"].append({"name": label, "evidence": line})
            if level >= 4 and re.search(r"第.{1,8}(?:章|节|幕)|开头|中段|结尾", label):
                manifest["timeline"].append({"name": label, "evidence": line})
            continue
        bullet = re.match(r"^[-*+]\s*\*\*([^*\n]{2,30})\*\*\s*[：:]\s*(.+)$", line)
        if not bullet:
            continue
        label, detail = bullet.groups()
        item = {"name": detail[:80].strip(), "evidence": line}
        if re.search(r"伏笔|铺垫|承诺|回收|兑现", label):
            manifest["promises"].append(item)
        elif re.search(r"钩子|谜团|悬念|问题|留白", label):
            manifest["questions"].append(item)
        elif any(term in section for term in ("写作要点", "写作要求", "创作约束")):
            manifest["constraints"].append({"text": f"{label}：{detail}", "evidence": line})
    return {key: _dedupe_manifest_items(items) for key, items in manifest.items()}


def _dedupe_manifest_items(items: list[dict[str, str]]) -> list[dict[str, str]]:
    result = []
    seen = set()
    for item in items:
        identity = str(item.get("name") or item.get("text") or "").strip().casefold()
        if identity and identity not in seen:
            seen.add(identity)
            result.append(item)
    return result


def normalize_outline_manifest(manifest: dict) -> dict:
    """Collapse local/model labels that point to the same outline evidence."""
    result = {
        key: _dedupe_manifest_items([
            item for item in manifest.get(key, []) if isinstance(item, dict)
        ])
        for key in OUTLINE_MANIFEST_KEYS
    }
    for key in ("plot_arcs", "promises", "questions"):
        grouped: dict[str, dict] = {}
        order: list[str] = []
        for item in result[key]:
            evidence = re.sub(r"\s+", " ", str(item.get("evidence") or "")).strip().casefold()
            identity = evidence or str(item.get("name") or "").strip().casefold()
            if identity not in grouped:
                grouped[identity] = item
                order.append(identity)
                continue
            current_name = str(item.get("name") or "").strip()
            saved_name = str(grouped[identity].get("name") or "").strip()
            if current_name and len(current_name) < len(saved_name):
                grouped[identity] = item
        result[key] = [grouped[identity] for identity in order]
    result.update({key: value for key, value in manifest.items()
                   if key not in OUTLINE_MANIFEST_KEYS})
    return result


def _validated_manifest(value: dict, content: str) -> dict[str, list[dict[str, str]]]:
    result = {key: [] for key in OUTLINE_MANIFEST_KEYS}
    for key in OUTLINE_MANIFEST_KEYS:
        raw_items = value.get(key)
        if not isinstance(raw_items, list):
            continue
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            evidence = str(raw.get("evidence") or "").strip()
            identity_key = "text" if key == "constraints" else "name"
            identity = str(raw.get(identity_key) or "").strip()
            if not identity or not evidence or evidence not in content:
                continue
            if key in {"characters", "locations"} and identity not in evidence:
                continue
            item = {identity_key: identity[:120], "evidence": evidence[:300]}
            if key == "characters":
                role = str(raw.get("role") or "supporting").strip().lower()
                item["role"] = role if role in {
                    "protagonist", "counterpart", "antagonist", "supporting", "minor",
                } else "supporting"
            elif key == "world":
                item["kind"] = str(raw.get("kind") or "setting").strip()[:40]
            result[key].append(item)
    return {key: _dedupe_manifest_items(items) for key, items in result.items()}


def _merge_manifests(*manifests: dict) -> dict[str, list[dict[str, str]]]:
    return normalize_outline_manifest({
        key: _dedupe_manifest_items([
            item for manifest in manifests for item in manifest.get(key, [])
        ])
        for key in OUTLINE_MANIFEST_KEYS
    })


def _json_object(text: str) -> dict:
    try:
        return parse_json_object(text, label="资料清单")
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"资料清单没有返回唯一有效 JSON：{exc}") from exc


def _ltp_entity_candidates(text: str, payload: dict) -> list[dict[str, str]]:
    if not isinstance(payload, dict) or not payload.get("available"):
        return []
    result = payload.get("result") or {}
    words = result.get("cws") or []
    words = words[0] if words and isinstance(words[0], list) else words
    entities = result.get("ner") or []
    entities = entities[0] if entities and isinstance(entities[0], list) else entities
    candidates = []
    for entity in entities:
        if not isinstance(entity, (list, tuple)) or len(entity) < 3:
            continue
        try:
            if len(entity) >= 4 and isinstance(entity[1], str):
                label, start, end = str(entity[0]), int(entity[2]), int(entity[3])
            else:
                label, start, end = str(entity[0]), int(entity[1]), int(entity[2])
        except (TypeError, ValueError):
            continue
        if not 0 <= start <= end < len(words):
            continue
        value = "".join(map(str, words[start:end + 1])).strip()
        if value and value in text:
            candidates.append({"text": value, "type": label})
    return _dedupe_manifest_items([
        {"name": item["text"], "evidence": item["text"], "kind": item["type"]}
        for item in candidates
    ])[:80]


def _outline_section_title(value: str) -> str:
    title = unicodedata.normalize("NFKC", str(value or "")).strip()
    title = _OUTLINE_SECTION_NUMBER.sub("", title).strip().rstrip(":/ \t")
    title = re.sub(r"\s*\([^()]*\)\s*$", "", title).strip()
    return title.rstrip(":/ \t")


def outline_event_kind(section: str, label: str) -> str:
    """Classify outline labels so non-story constraints never become chronology."""
    section = unicodedata.normalize("NFKC", str(section or "")).strip()
    label = unicodedata.normalize("NFKC", str(label or "")).strip()
    section_title = _outline_section_title(section)
    label_title = _outline_section_title(label)
    if section_title in _OUTLINE_THEME_SECTIONS:
        return "theme"
    if section_title in _OUTLINE_DIRECTIVE_SECTIONS:
        return "directive"
    if label_title == section_title and section_title in _OUTLINE_STRUCTURE_SECTIONS:
        return "structure"
    chapter = _OUTLINE_CHAPTER_LABEL.match(label)
    if chapter:
        suffix = chapter.group("suffix").strip().strip("·：:-— ")
        return "narrative" if suffix else "structure"
    if _OUTLINE_STRUCTURE_LABEL.match(label):
        return "structure"
    return "narrative"


def _outline_event_anchor(label: str) -> bool:
    label = unicodedata.normalize("NFKC", str(label or "")).strip()
    return bool(
        _OUTLINE_CHAPTER_LABEL.match(label) or _OUTLINE_STRUCTURE_LABEL.match(label)
    )


def _outline_anchor_level(label: str) -> int:
    """Return nesting rank: chapter < act < part/volume."""
    label = unicodedata.normalize("NFKC", str(label or "")).strip()
    if _OUTLINE_CHAPTER_LABEL.match(label):
        return 1
    if not _OUTLINE_STRUCTURE_LABEL.match(label):
        return 0
    if re.match(r"^(?:第.+幕|act\b)", label, flags=re.IGNORECASE):
        return 2
    return 3


def narrative_outline_events(events: list[dict]) -> list[dict]:
    """Return executable story events, using structural headings only as sparse fallbacks."""
    classified: list[tuple[dict, str, int, int]] = []
    for event in events:
        kind = str(event.get("kind") or "")
        if kind not in OUTLINE_EVENT_KINDS:
            kind = outline_event_kind(event.get("section", ""), event.get("label", ""))
        label = str(event.get("label") or "").strip()
        classified.append((
            event, kind, _outline_anchor_level(label),
            int(event.get("_source_level") or 0),
        ))

    result = []
    for index, (event, kind, level, source_level) in enumerate(classified):
        if source_level:
            following_has_nested_event = False
            for (
                _following, following_kind, _following_level,
                following_source_level,
            ) in classified[index + 1:]:
                if (
                    following_source_level
                    and following_source_level <= source_level
                ):
                    break
                if following_kind == "narrative" and (
                    not following_source_level
                    or following_source_level > source_level
                ):
                    following_has_nested_event = True
                    break
            if following_has_nested_event:
                continue
        if level:
            following_has_executable_descendant = False
            for (
                _following, following_kind, following_level,
                _following_source_level,
            ) in classified[index + 1:]:
                if following_level >= level:
                    break
                if (
                    following_level
                    or following_kind == "narrative" and not following_level
                ):
                    following_has_executable_descendant = True
                    break
            if (
                not following_has_executable_descendant
                and kind in {"narrative", "structure"}
            ):
                result.append(event)
            continue
        if kind == "narrative":
            result.append(event)
    return result


def _outline_event_records(content: str) -> list[dict]:
    """Build stable outline records with transient hierarchy and exact evidence blocks."""
    lines = _visible_outline_markdown(content).splitlines()
    events: list[dict] = []
    section = ""
    occurrences: dict[str, int] = {}
    for line_index, line in enumerate(lines):
        heading = re.match(
            r"^(?P<marks>#{2,4})[ \t]+(?P<label>.+?)\s*$", line.strip(),
        )
        source_level = 0
        if heading:
            label = heading.group("label").strip()
            level = len(heading.group("marks"))
            source_level = level
            if level == 2:
                section = label
            candidate = label if (
                level >= 3
                or not any(term in label for term in ("大纲", "剧情", "人物", "角色", "设定", "总览"))
            ) else ""
        else:
            bold = re.match(r"^\s*(?:[-*]\s*)?\*\*([^*\n]{2,80})\*\*", line)
            candidate = bold.group(1).strip() if bold else ""
        candidate = re.sub(r"[：:]\s*$", "", candidate).strip()
        if (
            not candidate or len(candidate) > 50
            or any(term in candidate for term in OUTLINE_EVENT_SKIP_TERMS)
            or any(term in section for term in ("人物", "角色"))
        ):
            continue
        identity_text = unicodedata.normalize("NFKC", f"{section}|{candidate}")
        normalized = re.sub(r"\W+", "", identity_text, flags=re.UNICODE).casefold()
        if not normalized:
            continue
        occurrences[normalized] = occurrences.get(normalized, 0) + 1
        identity = f"{normalized}|{occurrences[normalized]}"
        events.append({
            "id": "EV-" + hashlib.sha1(identity.encode("utf-8")).hexdigest()[:8],
            "order": len(events) + 1, "label": candidate, "section": section,
            "_line_index": line_index,
            "_source_level": source_level,
        })
    for index, event in enumerate(events):
        start = int(event["_line_index"])
        end = (
            int(events[index + 1]["_line_index"])
            if index + 1 < len(events) else len(lines)
        )
        event["evidence"] = "\n".join(lines[start:end]).strip()
    return events


def outline_events(content: str) -> list[dict[str, str | int]]:
    """Build stable event IDs from explicit event labels in a confirmed outline."""
    return [{
        key: value for key, value in event.items()
        if not key.startswith("_") and key != "evidence"
    } for event in _outline_event_records(content)]


def narrative_outline_event_contracts(content: str) -> list[dict]:
    """Derive lossless, genre-neutral executable events without changing stored outlines."""
    records = _outline_event_records(content)
    selected_ids = {
        str(item.get("id") or "") for item in narrative_outline_events(records)
    }
    selected = [
        item for item in records if str(item.get("id") or "") in selected_ids
    ]
    contracts = []
    for order, item in enumerate(selected, 1):
        contracts.append({
            "id": str(item["id"]),
            "order": order,
            "source_order": int(item["order"]),
            "label": str(item["label"]),
            "section": str(item["section"]),
            "kind": "narrative",
            "source": "formal_outline",
            "evidence": str(item.get("evidence") or item["label"]),
            "presentation_order": order,
            "story_time": "",
            "timeline": "",
            "actor": "",
            "location": "",
            "viewpoint": "",
            "knowledge_delta": [],
            "relationship_delta": [],
        })
    return contracts


def _confirmed_value(state: dict, key: str) -> str:
    for item in state.get("confirmed_facts", []):
        if isinstance(item, dict) and item.get("key") == key:
            return str(item.get("value") or "").strip()
    return ""


def _character_profile(project_path: Path, role: str) -> str:
    for path in sorted((project_path / "characters").glob("*.md")):
        if path.name == "_index.md":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        name = re.search(r'(?m)^name:\s*["\']?([^"\'\r\n]+)', text)
        profile_role = re.search(r"(?m)^role:\s*([^\r\n]+)", text)
        if role == "protagonist" and profile_role and profile_role.group(1).strip() == role:
            return name.group(1).strip() if name else ""
        if role == "counterpart" and name and profile_role and (
                profile_role.group(1).strip() == "deuteragonist"
                or re.search(r"公子|少爷|世子|从嘲笑.*(?:守护|真香)", text)):
            return name.group(1).strip()
    return ""


def canon_profile(project, state: dict) -> dict[str, dict[str, str | bool]]:
    requirements = project.metadata.get("story_requirements") or {}
    protagonist = (
        _confirmed_value(state, "outline.protagonist")
        or str(requirements.get("protagonist.name") or "").strip()
        or _character_profile(project.path, "protagonist")
    )
    locations = str(requirements.get("world.locations") or "")
    location = _confirmed_value(state, "outline.primary_location")
    if not location:
        match = re.search(r"([\u4e00-\u9fff]{1,6}(?:府|宫|庄|村|城|镇|国|朝))", locations)
        location = match.group(1) if match else ""
    counterpart = (
        _confirmed_value(state, "outline.counterpart")
        or _character_profile(project.path, "counterpart")
    )
    locked_keys = {
        str(item.get("key")) for item in state.get("locked_facts", [])
        if isinstance(item, dict)
    }
    return {
        "protagonist": {
            "label": "主角姓名", "value": protagonist,
            "locked": "protagonist.name" in locked_keys,
        },
        "primary_location": {
            "label": "主要府邸或地点", "value": location, "locked": False,
        },
        "counterpart": {
            "label": "主要公子", "value": counterpart, "locked": False,
        },
    }


def detect_canon_conflicts(project, state: dict, content: str) -> list[dict]:
    profile = canon_profile(project, state)
    characters = extract_outline_characters(content)
    protagonist_candidate = next(
        (item["name"] for item in characters if item["role"] == "protagonist"), "",
    )
    if not protagonist_candidate:
        match = re.search(
            r"(?:孤女|丫头|女子|少女|姑娘)([\u4e00-\u9fff]{2,4})被", content,
        )
        protagonist_candidate = match.group(1) if match else ""
    counterpart_candidate = next(
        (item["name"] for item in characters if item["role"] == "counterpart"), "",
    )
    ignored_locations = {"府中", "府里", "府内", "府外", "府邸"}
    location_counts: dict[str, int] = {}
    expected_location = str(profile["primary_location"]["value"])
    for raw_value in re.findall(r"[\u4e00-\u9fff]{1,6}(?:府|宫|庄|村|城|镇|国|朝)", content):
        value = (
            raw_value[-len(expected_location):]
            if expected_location and raw_value.endswith(expected_location[-1])
            and len(raw_value) >= len(expected_location)
            else raw_value
        )
        if value not in ignored_locations:
            location_counts[value] = location_counts.get(value, 0) + 1
    location_candidate = next((
        value for value, _count in sorted(
            location_counts.items(), key=lambda item: (-item[1], item[0]),
        ) if value != expected_location
    ), "")
    candidates = {
        "protagonist": protagonist_candidate,
        "primary_location": location_candidate,
        "counterpart": counterpart_candidate,
    }
    conflicts = []
    for key, candidate_value in candidates.items():
        current_value = str(profile[key]["value"] or "")
        if not current_value or not candidate_value or candidate_value == current_value:
            continue
        if current_value in content and key != "primary_location":
            explanation = f"候选大纲同时出现“{current_value}”和“{candidate_value}”，后续容易混用。"
        elif current_value in content:
            explanation = f"候选大纲混用了“{current_value}”和“{candidate_value}”两个地点。"
        else:
            explanation = f"项目资料写的是“{current_value}”，候选大纲改成了“{candidate_value}”。"
        identity = hashlib.sha1(
            f"{key}|{current_value}|{candidate_value}".encode("utf-8"),
        ).hexdigest()[:16]
        conflicts.append({
            "id": identity, "key": key, "label": profile[key]["label"],
            "current_value": current_value, "candidate_value": candidate_value,
            "locked": bool(profile[key]["locked"]),
            "can_use_candidate": not bool(profile[key]["locked"]),
            "explanation": explanation,
        })
    return conflicts


@dataclass(frozen=True)
class OutlineBlock:
    index: int
    label: str
    text: str


class OutlineService:
    def __init__(self, db: Database, projects: ProjectStore, gateway=None, local_nlp=None) -> None:
        self.db = db
        self.projects = projects
        self.gateway = gateway
        self.local_nlp = local_nlp
        self.states = StoryStateStore(db)

    async def material_manifest(self, project_id: str) -> dict:
        project = self.projects.get(project_id)
        current = self.current(project_id)
        content = str(current.get("content") or "")
        if not content:
            raise ValueError("还没有正式大纲，无法建立资料清单")
        outline_hash = self._hash(content)
        cache = project.path / "memory" / "outline-manifest.json"
        try:
            saved = json.loads(cache.read_text(encoding="utf-8"))
            if (
                saved.get("outline_hash") == outline_hash
                and isinstance(saved.get("manifest"), dict)
                and saved["manifest"].get("_review", {}).get("status") != "local_only"
            ):
                return normalize_outline_manifest(saved["manifest"])
        except (OSError, json.JSONDecodeError):
            pass

        local = local_outline_manifest(content)
        nlp_payload = self.local_nlp.analyze(content) if self.local_nlp else {}
        nlp_candidates = _ltp_entity_candidates(content, nlp_payload)
        model = {key: [] for key in OUTLINE_MANIFEST_KEYS}
        review = {
            "status": "local_only",
            "message": "规划模型暂时不可用，本次使用正式大纲的明确结构继续准备。",
        }
        model_name = ""
        if self.gateway is not None:
            try:
                response = await self.gateway.complete(
                    "planning",
                    "从正式大纲中提取初始化资料清单，只提取原文明确支持的内容，禁止补写、合并人物或猜测别名。"
                    "返回严格 JSON，键固定为 characters、world、locations、plot_arcs、timeline、promises、"
                    "questions、constraints。characters 每项含 name、role、evidence；world 每项含 name、kind、"
                    "evidence；其余除 constraints 外每项含 name、evidence；constraints 每项含 text、evidence。"
                    "evidence 必须逐字摘自正式大纲。人物和地点的 name 必须逐字出现在自己的 evidence 中。"
                    "role 只能是 protagonist、counterpart、antagonist、supporting、minor。"
                    "普通描写、性格、目标和章节标签不能当成人物或地点。",
                    json.dumps({
                        "confirmed_outline": content,
                        "local_markdown_findings": local,
                        "local_nlp_candidates": nlp_candidates,
                    }, ensure_ascii=False),
                    max_output_tokens=4096,
                )
                model = _validated_manifest(_json_object(response.text), content)
                model_name = str(response.receipt.get("model_name") or "")
                review = {"status": "model_confirmed", "message": "规划模型已按正式大纲原文复核资料清单。"}
            except Exception:
                pass
        manifest = _merge_manifests(local, model)
        manifest["_review"] = review
        atomic_write(cache, json.dumps({
            "outline_hash": outline_hash,
            "outline_version": current.get("outline_version", 0),
            "manifest": manifest,
            "model": model_name,
        }, ensure_ascii=False, indent=2) + "\n")
        return manifest

    def current(self, project_id: str) -> dict:
        project = self.projects.get(project_id)
        state = self.states.ensure(project_id, project.path)
        outline = state.data.get("outline")
        manuscript = project.path / "manuscript" / "story.md"
        manuscript_exists = manuscript.is_file() and bool(manuscript.read_text(encoding="utf-8").strip())
        if isinstance(outline, dict) and str(outline.get("content") or "").strip():
            content = self._clean_content(str(outline["content"]))
            source = str(outline.get("source") or "candidate")
            version = int(outline.get("version") or 1)
            updated_at = outline.get("updated_at")
            events = outline_events(content)
        else:
            content = self._legacy_outline(project_id, project.path)
            source = "legacy_run" if content else "none"
            version = 0
            updated_at = None
            events = outline_events(content)
        stage = "manuscript_started" if manuscript_exists else "outline_only" if content else "no_outline"
        return {
            "exists": bool(content), "content": content, "source": source,
            "outline_version": version, "state_revision": state.revision,
            "updated_at": updated_at, "stage": stage,
            "events": events,
            "manuscript_exists": manuscript_exists,
            "message": self._stage_message(stage),
        }

    def create_candidate(self, project_id: str, content: str, *, title: str = "候选大纲",
                         metadata: dict | None = None) -> dict:
        project = self.projects.get(project_id)
        content = self._clean_content(content)
        state = self.states.ensure(project_id, project.path)
        created_at = self._now()
        base_metadata = {
            **(metadata or {}), "title": self._clean_title(title), "created_at": created_at,
        }
        candidate = self.states.create_candidate(
            project_id, None, state.revision, "outline", self._hash(content), base_metadata,
        )
        relative = Path("learning") / "candidates" / f"outline-{candidate.id}.md"
        try:
            atomic_write(project.path / relative, content)
            candidate = self.states.update_candidate(
                candidate.id, content_hash=self._hash(content),
                metadata={**base_metadata, "relative_path": relative.as_posix()},
            )
        except Exception:
            self.states.reject(candidate.id, "candidate file write failed")
            raise
        return self._public_candidate(candidate, content)

    def list_candidates(self, project_id: str, *, include_resolved: bool = False) -> list[dict]:
        self.projects.get(project_id)
        status = None if include_resolved else "pending"
        result = []
        for candidate in self.states.list_candidates(project_id, kind="outline", status=status):
            try:
                result.append(self._public_candidate(candidate, self._candidate_content(project_id, candidate)))
            except (OSError, ValueError):
                result.append({
                    "id": candidate.id, "status": candidate.status,
                    "title": candidate.metadata.get("title") or "候选大纲",
                    "created_at": candidate.metadata.get("created_at"),
                    "content": "", "available": False,
                    "message": "候选文件不可用，请放弃后重新生成。",
                })
        return result

    def get_candidate(self, project_id: str, candidate_id: str) -> dict:
        candidate = self._candidate(project_id, candidate_id)
        return self._public_candidate(candidate, self._candidate_content(project_id, candidate))

    def update_candidate(self, project_id: str, candidate_id: str, content: str,
                         *, title: str | None = None) -> dict:
        project = self.projects.get(project_id)
        candidate = self._candidate(project_id, candidate_id)
        content = self._clean_content(content)
        path = self._candidate_path(project.path, candidate)
        old_content = path.read_text(encoding="utf-8") if path.is_file() else None
        atomic_write(path, content)
        metadata = {
            **candidate.metadata,
            "title": self._clean_title(title or candidate.metadata.get("title") or "候选大纲"),
            "updated_at": self._now(),
        }
        try:
            updated = self.states.update_candidate(
                candidate_id, content_hash=self._hash(content), metadata=metadata,
            )
        except Exception:
            if old_content is not None:
                atomic_write(path, old_content)
            raise
        return self._public_candidate(updated, content)

    def reject_candidate(self, project_id: str, candidate_id: str, reason: str = "") -> dict:
        candidate = self._candidate(project_id, candidate_id)
        self.states.reject(candidate.id, reason or "用户放弃候选大纲")
        rejected = self.states.get_candidate(candidate.id)
        assert rejected is not None
        return self._public_candidate(rejected, self._candidate_content(project_id, rejected))

    def create_project_from_candidate(self, project_id: str, candidate_id: str) -> dict:
        source = self.projects.get(project_id)
        candidate = self._candidate(project_id, candidate_id)
        content = self._candidate_content(project_id, candidate)
        return self._create_project_from_outline(
            source, content, candidate.metadata.get("title"), candidate_id,
        )

    def create_project_from_current(self, project_id: str) -> dict:
        source = self.projects.get(project_id)
        current = self.current(project_id)
        readiness = self.writing_readiness(project_id)
        if not current["exists"]:
            raise ValueError("当前作品还没有正式大纲")
        if readiness["ready"]:
            raise ValueError("当前正式大纲与项目资料没有冲突，不需要另建作品")
        return self._create_project_from_outline(
            source, current["content"], source.title, None,
        )

    def _create_project_from_outline(self, source, content: str,
                                     fallback_title: str | None,
                                     source_candidate_id: str | None) -> dict:
        heading = re.search(r"(?m)^#\s+(.+)$", content)
        base_title = self._project_title_from_outline(
            heading.group(1) if heading else "", fallback_title or source.title,
        )
        paragraphs = [
            value.strip() for value in re.split(r"\n\s*\n", content)
            if value.strip() and not value.lstrip().startswith(("#", "|", "---"))
        ]
        premise = (paragraphs[0] if paragraphs else source.metadata.get("premise") or base_title)[:2000]
        created = self.projects.create(ProjectCreate(
            title=f"{base_title}（新大纲）",
            mode=source.mode,
            genre=str(source.metadata.get("genre") or "未分类"),
            premise=premise,
            target_words=int(source.metadata.get("target_words") or 10_000),
            pov=str(source.metadata.get("pov") or "third-limited"),
            tone=str(source.metadata.get("tone") or "natural"),
        ))
        metadata_path = created.path / "project.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        for key in (
            "initialization_skills", "platform", "platform_profile_id",
            "platform_profile_version", "optimized_local_review_enabled",
        ):
            if key in source.metadata:
                metadata[key] = source.metadata[key]
        metadata.update({
            "source_project_id": source.id,
            "source_outline_candidate_id": source_candidate_id,
            "materials_need_generation": True,
            "story_requirements": {
                "title": metadata["title"], "genre": metadata["genre"],
                "premise": metadata["premise"], "target_words": metadata["target_words"],
                "pov": metadata["pov"], "tone": metadata["tone"],
            },
        })
        if not metadata.get("initialization_skills"):
            metadata["initialization_skills"] = [
                "story-init", "character-management", "worldbuilding", "plot-structure",
            ]
        atomic_write(metadata_path, json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
        requirements = metadata["story_requirements"]
        details = "\n\n## Confirmed Story Requirements\n\n" + "\n".join(
            f"- **{key}**: {value}"
            for key, value in requirements.items() if value not in (None, "")
        )
        story_path = created.path / "story.md"
        atomic_write(story_path, story_path.read_text(encoding="utf-8") + details)
        new_candidate = self.create_candidate(
            created.id, content, title="新作品第一版大纲",
            metadata={
                "source_project_id": source.id,
                "source_candidate_id": source_candidate_id,
            },
        )
        self.apply_candidate(created.id, new_candidate["id"])
        result = self.projects.get(created.id)
        return {
            **result.metadata, "path": str(result.path),
            "message": "新作品和第一版正式大纲已创建；人物与设定将在你确认后重新生成。",
        }

    def compare_candidate(self, project_id: str, candidate_id: str) -> dict:
        project = self.projects.get(project_id)
        current = self.current(project_id)
        candidate = self.get_candidate(project_id, candidate_id)
        changes = self._compare(current["content"], candidate["content"])
        summary = {
            "added": sum(item["type"] == "added" for item in changes),
            "removed": sum(item["type"] == "removed" for item in changes),
            "changed": sum(item["type"] in {"changed", "reordered", "uncertain"} for item in changes),
            "uncertain": sum(item["type"] == "uncertain" for item in changes),
        }
        state = self.states.get(project_id)
        assert state is not None
        lock_failures = validate_locked_facts(current["content"], candidate["content"], state.data)
        canon_conflicts = detect_canon_conflicts(project, state.data, candidate["content"])
        risks = []
        if current["manuscript_exists"]:
            risks.append("作品已经有正文；应用后只改变后续创作依据，不会修改现有正文。")
        if summary["removed"]:
            risks.append(f"候选版本删除了 {summary['removed']} 个剧情块，请确认伏笔和结局仍能兑现。")
        if lock_failures:
            risks.append("候选版本遗漏了已锁定设定，当前不能应用。")
        if canon_conflicts:
            risks.append(f"发现 {len(canon_conflicts)} 处项目资料与候选大纲不一致，请先逐项决定。")
        market_check = self._market_check(project, candidate["content"])
        return {
            "project_id": project_id, "candidate_id": candidate_id,
            "state_revision": current["state_revision"], "stage": current["stage"],
            "current": current, "candidate": candidate, "changes": changes,
            "summary": summary, "risks": risks, "lock_failures": lock_failures,
            "canon_conflicts": canon_conflicts,
            "market_check": market_check,
            "can_apply": not lock_failures and not canon_conflicts, "model_called": False,
            "semantic_review_recommended": bool(summary["uncertain"]),
        }

    def _market_check(self, project, candidate: str) -> dict:
        if project.metadata.get("market_baseline_enabled") is not True:
            return {
                "status": "not_enabled", "sample_count": 0, "advisory_only": True,
                "message": "当前作品没有启用同类市场参考。", "signals": [],
                "mechanisms": [],
            }
        baseline = self.projects.active_learning_data(project.id, "market_baseline")
        reference = compact_market_reference(baseline)
        result = {**reference, "signals": []}
        if reference["status"] in {"unavailable", "insufficient"}:
            return result
        opening = self._outline_opening(candidate)
        if not opening:
            return {
                **result,
                "message": reference["message"] + " 候选大纲没有单独标出开头段，暂不比较开头信号。",
            }
        for signal, label, pattern, percent in (
            (
                "opening_question", "明确问题", _OUTLINE_QUESTION_SIGNAL,
                reference["opening"].get("question_percent", 0),
            ),
            (
                "opening_anomaly", "异常或冲突", _OUTLINE_ANOMALY_SIGNAL,
                reference["opening"].get("anomaly_percent", 0),
            ),
        ):
            if percent < 50:
                continue
            detected = bool(pattern.search(opening))
            result["signals"].append({
                "signal": signal, "label": label, "detected": detected,
                "sample_percent": percent,
                "message": (
                    f"候选开头已出现{label}，与这组同类样本的常见信号一致。"
                    if detected else
                    f"同类样本中约 {percent:g}% 的开头出现{label}；候选开头暂未明确出现，是否补充由你决定。"
                ),
            })
        return result

    @classmethod
    def _outline_opening(cls, content: str) -> str:
        for block in cls._blocks(content):
            if re.search(r"开头|开篇|起始|第一章|第一幕", block.label):
                return block.text[:1200]
        return ""

    def apply_candidate(self, project_id: str, candidate_id: str, *,
                        change_ids: list[str] | None = None,
                        expected_revision: int | None = None,
                        allow_full_with_manuscript: bool = False,
                        source: str = "candidate",
                        canon_choices: dict[str, str] | None = None) -> dict:
        project = self.projects.get(project_id)
        candidate = self._candidate(project_id, candidate_id)
        candidate_content = self._candidate_content(project_id, candidate)
        current = self.current(project_id)
        if current["manuscript_exists"] and change_ids is None and not allow_full_with_manuscript:
            raise ValueError("作品已有正文；整体应用前需要再次确认，现有正文不会被修改")
        report = self.compare_candidate(project_id, candidate_id)
        if expected_revision is not None and expected_revision != report["state_revision"]:
            raise ValueError("当前大纲已经变化，请刷新比较结果后再应用")
        if report["lock_failures"]:
            raise ValueError("候选大纲遗漏了锁定设定，不能应用")
        content = (
            candidate_content if change_ids is None
            else self._merge_selected(current["content"], candidate_content, report["changes"], change_ids)
        )
        state = self.states.get(project_id)
        if state is None:
            raise LookupError("StoryState not found")
        final_conflicts = detect_canon_conflicts(project, state.data, content)
        choices = canon_choices or {}
        unresolved = [item for item in final_conflicts if choices.get(item["id"]) not in {
            "keep_current", "use_candidate",
        }]
        if unresolved:
            raise ValueError("请先决定每一处设定冲突最终采用哪一项")
        confirmed_facts = list(state.data.get("confirmed_facts", []))
        for item in final_conflicts:
            choice = choices[item["id"]]
            if choice == "use_candidate" and not item["can_use_candidate"]:
                raise ValueError(f"“{item['label']}”已被锁定，请先在项目资料中修改")
            if choice == "keep_current":
                content = content.replace(item["candidate_value"], item["current_value"])
                continue
            fact_key = f"outline.{item['key']}"
            confirmed_facts = [
                fact for fact in confirmed_facts
                if not isinstance(fact, dict) or fact.get("key") != fact_key
            ]
            confirmed_facts.append({
                "key": fact_key, "value": item["candidate_value"],
                "level": "confirmed", "source": f"outline:{candidate_id}",
            })
        lock_failures = validate_locked_facts(current["content"], content, state.data)
        if lock_failures:
            raise ValueError("候选大纲遗漏了锁定设定，不能应用")
        version = current["outline_version"] + 1
        outline = {
            "content": content, "version": version, "source": source,
            "candidate_id": candidate_id, "updated_at": self._now(),
            "content_hash": self._hash(content),
            "events": outline_events(content),
        }
        committed = self.states.commit(
            candidate_id, expected_revision or state.revision,
            {**state.data, "confirmed_facts": confirmed_facts, "outline": outline},
        )
        atomic_write(project.path / "plot" / "outline.md", content)
        self._mark_outline_artifacts_stale(project.path, project_id)
        return {
            **self.current(project_id), "story_state_revision": committed.revision,
            "formal_manuscript_changed": False,
        }

    def history(self, project_id: str) -> list[dict]:
        self.projects.get(project_id)
        result = []
        for state in self.states.history(project_id):
            outline = state.data.get("outline")
            if not isinstance(outline, dict) or not str(outline.get("content") or "").strip():
                continue
            result.append({
                "outline_version": int(outline.get("version") or 1),
                "story_state_revision": state.revision,
                "source": outline.get("source") or "candidate",
                "updated_at": outline.get("updated_at"),
                "content": self._clean_content(str(outline["content"])),
                "is_current": False,
            })
        if result:
            result[-1]["is_current"] = True
        return result

    def restore(self, project_id: str, *, outline_version: int) -> dict:
        target = next(
            (item for item in self.history(project_id) if item["outline_version"] == outline_version),
            None,
        )
        if target is None:
            raise LookupError("大纲历史版本不存在")
        candidate = self.create_candidate(
            project_id, target["content"], title=f"恢复第 {outline_version} 版",
            metadata={"restores_outline_version": outline_version},
        )
        return self.apply_candidate(
            project_id, candidate["id"], allow_full_with_manuscript=True, source="restored",
        )

    def overview(self, project_id: str) -> dict:
        return {
            "current": self.current(project_id),
            "candidates": self.list_candidates(project_id),
            "history": self.history(project_id),
            "writing_readiness": self.writing_readiness(project_id),
        }

    def writing_readiness(self, project_id: str) -> dict:
        project = self.projects.get(project_id)
        current = self.current(project_id)
        if not current["exists"]:
            return {
                "ready": False, "conflicts": [],
                "message": "请先确认一份正式大纲，再开始准备人物或生成正文。",
            }
        state = self.states.ensure(project_id, project.path)
        conflicts = detect_canon_conflicts(project, state.data, current["content"])
        return {
            "ready": not conflicts, "conflicts": conflicts,
            "message": (
                "正式大纲与项目资料一致，可以进入后续写作。" if not conflicts else
                f"正式大纲与项目资料有 {len(conflicts)} 处冲突，请先生成修正版候选并重新确认。"
            ),
        }

    async def semantic_review(self, project_id: str, candidate_id: str) -> dict:
        report = self.compare_candidate(project_id, candidate_id)
        uncertain = [item for item in report["changes"] if item["type"] == "uncertain"]
        if not uncertain:
            return report
        if self.gateway is None:
            raise ValueError("规划模型当前不可用，请先检查模型配置")
        state = self.states.get(project_id)
        locked_facts = (state.data.get("locked_facts") if state else []) or []
        evidence = [{
            "id": item["id"], "type": item["type"], "label": item["label"],
            "current_text": item["current_text"][:1_000],
            "candidate_text": item["candidate_text"][:1_000],
        } for item in uncertain[:10]]
        user = json.dumps({
            "changes": evidence,
            "locked_facts": locked_facts[:20],
        }, ensure_ascii=False, indent=2)
        result = await self.gateway.complete(
            "planning",
            "你只判断候选大纲中本地程序无法确定的变化。返回 JSON，不改写大纲。"
            "格式：{\"decisions\":[{\"id\":\"变化ID\",\"type\":\"changed或reordered\","
            "\"explanation\":\"一句易懂说明\",\"impact\":\"会影响哪里\"}]}。",
            user[:30_000], max_output_tokens=2048,
        )
        decisions = self._semantic_decisions(result.text, {item["id"] for item in uncertain})
        by_id = {item["id"]: item for item in decisions}
        changes = []
        for item in report["changes"]:
            decision = by_id.get(item["id"])
            changes.append({**item, **decision} if decision else item)
        report["changes"] = changes
        report["summary"] = {
            "added": sum(item["type"] == "added" for item in changes),
            "removed": sum(item["type"] == "removed" for item in changes),
            "changed": sum(item["type"] in {"changed", "reordered", "uncertain"} for item in changes),
            "uncertain": sum(item["type"] == "uncertain" for item in changes),
        }
        report["model_called"] = True
        report["semantic_review_recommended"] = bool(report["summary"]["uncertain"])
        report["model_receipt"] = result.receipt
        return report

    def _legacy_outline(self, project_id: str, project_path: Path) -> str:
        for run in self.db.list_runs(project_id):
            if run["status"] != "completed":
                continue
            path = project_path / "runs" / run["id"] / "outputs" / "planning.md"
            if path.is_file() and (content := path.read_text(encoding="utf-8")).strip():
                return self._clean_content(content)
        return ""

    def _candidate(self, project_id: str, candidate_id: str):
        self.projects.get(project_id)
        candidate = self.states.get_candidate(candidate_id)
        if candidate is None or candidate.project_id != project_id or candidate.kind != "outline":
            raise LookupError("候选大纲不存在")
        return candidate

    def _candidate_content(self, project_id: str, candidate) -> str:
        project = self.projects.get(project_id)
        path = self._candidate_path(project.path, candidate)
        content = self._clean_content(path.read_text(encoding="utf-8"))
        if self._hash(content) != candidate.content_hash:
            raise ValueError("候选大纲内容与保存记录不一致，请重新生成")
        return content

    @staticmethod
    def _candidate_path(project_path: Path, candidate) -> Path:
        raw = candidate.metadata.get("relative_path")
        if not raw:
            raise ValueError("候选大纲缺少文件记录")
        path = (project_path / raw).resolve()
        if not path.is_relative_to(project_path.resolve()):
            raise ValueError("候选大纲路径无效")
        return path

    @classmethod
    def _compare(cls, current: str, candidate: str) -> list[dict]:
        current_blocks = cls._blocks(current)
        candidate_blocks = cls._blocks(candidate)
        current_by_label = {block.label: block for block in current_blocks}
        candidate_by_label = {block.label: block for block in candidate_blocks}
        changes = []
        matched_current: set[int] = set()
        for block in candidate_blocks:
            existing = current_by_label.get(block.label)
            if existing is None:
                changes.append(cls._change("added", None, block, "候选版本新增了这一段剧情。"))
                continue
            matched_current.add(existing.index)
            ratio = difflib.SequenceMatcher(None, cls._normalize(existing.text), cls._normalize(block.text)).ratio()
            if ratio >= 0.985 and existing.index == block.index:
                continue
            change_type = "uncertain" if ratio < 0.30 else "reordered" if ratio >= 0.985 else "changed"
            explanation = {
                "changed": "同一剧情位置的内容发生了变化。",
                "reordered": "这段剧情在候选版本中的位置发生了变化。",
                "uncertain": "文字和结构变化较大，本地程序无法可靠判断是否仍是同一情节。",
            }[change_type]
            changes.append(cls._change(change_type, existing, block, explanation))
        for block in current_blocks:
            if block.index not in matched_current and block.label not in candidate_by_label:
                changes.append(cls._change("removed", block, None, "候选版本删除了这一段剧情。"))
        return sorted(changes, key=lambda item: (
            item["candidate_index"] if item["candidate_index"] is not None else 10_000 + item["current_index"]
        ))

    @classmethod
    def _merge_selected(cls, current: str, candidate: str, changes: list[dict],
                        selected_ids: list[str]) -> str:
        selected = {item["id"]: item for item in changes if item["id"] in set(selected_ids)}
        if len(selected) != len(set(selected_ids)):
            raise ValueError("选择的变化已经失效，请重新比较")
        blocks = list(cls._blocks(current))
        candidate_blocks = cls._blocks(candidate)
        by_current = {block.index: position for position, block in enumerate(blocks)}
        for item in sorted(selected.values(), key=lambda value: value["current_index"] or 0, reverse=True):
            current_index = item["current_index"]
            candidate_index = item["candidate_index"]
            if item["type"] == "removed" and current_index in by_current:
                blocks.pop(by_current[current_index])
            elif current_index is not None and candidate_index is not None and current_index in by_current:
                blocks[by_current[current_index]] = candidate_blocks[candidate_index]
            by_current = {block.index: position for position, block in enumerate(blocks)}
        additions = [item for item in selected.values() if item["type"] == "added"]
        for item in sorted(additions, key=lambda value: value["candidate_index"]):
            block = candidate_blocks[item["candidate_index"]]
            blocks.insert(min(item["candidate_index"], len(blocks)), block)
        return cls._clean_content("\n\n".join(block.text.strip() for block in blocks))

    @classmethod
    def _blocks(cls, content: str) -> list[OutlineBlock]:
        content = content.strip()
        if not content:
            return []
        lines = content.splitlines()
        chunks: list[list[str]] = []
        current: list[str] = []
        for line in lines:
            if re.match(r"^#{1,4}\s+\S", line) and current:
                chunks.append(current)
                current = [line]
            else:
                current.append(line)
        if current:
            chunks.append(current)
        if len(chunks) == 1 and not re.match(r"^#{1,4}\s+\S", chunks[0][0]):
            paragraphs = [part.strip() for part in re.split(r"\n\s*\n", content) if part.strip()]
            chunks = [part.splitlines() for part in paragraphs]
        result = []
        for index, chunk in enumerate(chunks):
            text = "\n".join(chunk).strip()
            heading = re.match(r"^#{1,4}\s+(.+)$", chunk[0].strip())
            label = heading.group(1).strip() if heading else f"第 {index + 1} 段"
            result.append(OutlineBlock(index, label, text))
        return result

    @classmethod
    def _change(cls, change_type: str, current: OutlineBlock | None,
                candidate: OutlineBlock | None, explanation: str) -> dict:
        identity = "|".join((
            change_type, str(current.index if current else ""),
            str(candidate.index if candidate else ""),
            current.text if current else "", candidate.text if candidate else "",
        ))
        return {
            "id": hashlib.sha1(identity.encode("utf-8")).hexdigest()[:16],
            "type": change_type, "label": (candidate or current).label,
            "current_index": current.index if current else None,
            "candidate_index": candidate.index if candidate else None,
            "current_text": current.text if current else "",
            "candidate_text": candidate.text if candidate else "",
            "explanation": explanation,
        }

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(r"\W+", "", value, flags=re.UNICODE).lower()

    @staticmethod
    def _semantic_decisions(text: str, allowed_ids: set[str]) -> list[dict]:
        try:
            payload = parse_json_object(text, label="大纲变化判断")
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError("模型没有返回可读取的判断结果，请重新尝试") from exc
        decisions = payload.get("decisions") if isinstance(payload, dict) else None
        if not isinstance(decisions, list):
            raise ValueError("模型判断结果缺少变化列表，请重新尝试")
        cleaned = []
        for item in decisions:
            if not isinstance(item, dict) or item.get("id") not in allowed_ids:
                continue
            raw_change_type = item.get("type")
            change_type = canonical_model_label(
                raw_change_type, OUTLINE_CHANGE_TYPE_ALIASES,
            ) or "uncertain"
            cleaned.append({
                "id": item["id"], "type": change_type,
                "raw_type": raw_change_type,
                "explanation": str(item.get("explanation") or "模型未补充说明")[:500],
                "impact": str(item.get("impact") or "尚未说明具体影响")[:500],
            })
        if not cleaned:
            raise ValueError("模型没有识别出可用的变化判断，请重新尝试")
        return cleaned

    def _mark_outline_artifacts_stale(self, project_path: Path, project_id: str) -> None:
        artifact_types = ("scene_briefs", "short_causal_chain")
        with self.db.connect() as connection:
            rows = connection.execute(
                "SELECT id,artifact_type FROM project_learning_artifacts a "
                "WHERE project_id=? AND status='active' "
                "AND artifact_type IN (?,?) AND version=("
                "SELECT MAX(version) FROM project_learning_artifacts "
                "WHERE project_id=a.project_id AND artifact_type=a.artifact_type)",
                (project_id, *artifact_types),
            ).fetchall()
            for row in rows:
                connection.execute(
                    "UPDATE project_learning_artifacts SET status='stale' WHERE id=?",
                    (row["id"],),
                )
        for row in rows:
            path = project_path / "learning" / f"{row['artifact_type']}.json"
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            value["status"] = "stale"
            atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")

    @staticmethod
    def _hash(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def _clean_title(title: str) -> str:
        value = str(title or "").strip()
        if not value or len(value) > 80:
            raise ValueError("候选大纲标题需要 1-80 个字符")
        return value

    @staticmethod
    def _project_title_from_outline(heading: str, fallback: str) -> str:
        value = str(heading or "").strip()
        quoted = re.match(r"^[《「『](.+?)[》」』]\s*(?:小说|故事)?大纲.*$", value)
        if quoted:
            return quoted.group(1).strip()
        value = re.sub(r"\s*(?:小说|故事)?(?:正式)?大纲\s*$", "", value).strip("《》「」『』 ")
        return value or str(fallback or "新作品").strip()

    @staticmethod
    def _clean_content(content: str) -> str:
        value = str(content or "").strip()
        if not value:
            raise ValueError("候选大纲不能为空")
        if len(value) > MAX_OUTLINE_CHARACTERS:
            raise ValueError("候选大纲不能超过 100,000 个字符")
        return value + "\n"

    @staticmethod
    def _public_candidate(candidate, content: str) -> dict:
        return {
            "id": candidate.id, "status": candidate.status,
            "title": candidate.metadata.get("title") or "候选大纲",
            "created_at": candidate.metadata.get("created_at"),
            "updated_at": candidate.metadata.get("updated_at"),
            "content": content, "available": True,
            "base_revision": candidate.base_revision,
            "message": "等待你查看和比较" if candidate.status == "pending" else "候选已处理",
        }

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _stage_message(stage: str) -> str:
        return {
            "no_outline": "当前还没有正式大纲，可以把候选版本设为初始大纲。",
            "outline_only": "当前已有大纲但尚无正文，可以整体应用或逐项选择变化。",
            "manuscript_started": "当前已有正文；应用大纲只影响后续创作，不会修改现有正文。",
        }[stage]
