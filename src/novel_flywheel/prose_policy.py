from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


KNOWN_BEATS = frozenset({
    "emotion_shift",
    "information_reveal",
    "relationship_change",
    "suspense_turn",
    "comic_turn",
})

BEAT_RULES = {
    "emotion_shift": ("情绪转折", "情绪突变", "emotional shift"),
    "information_reveal": ("信息揭示", "真相揭露", "information reveal"),
    "relationship_change": ("关系变化", "关系转折", "relationship change"),
    "suspense_turn": ("悬念建立", "悬念落点", "suspense"),
    "comic_turn": ("喜剧落点", "笑点", "comic turn"),
}

STYLE_FIELDS = (
    "summary",
    "sentence_rhythm",
    "paragraph_rhythm",
    "dialogue",
)

ABSOLUTE_SHORT_PERMISSION = (
    "全篇短句",
    "短句为主",
    "大量使用短句",
    "short sentences throughout",
)

ABSOLUTE_SHORT_PROHIBITION = (
    "禁止使用短句",
    "不得使用短句",
    "不用短句",
    "no short sentences",
)


@dataclass(frozen=True)
class ProseValidationPolicy:
    source_ids: tuple[str, ...] = ()
    authorized_short_beats: frozenset[str] = frozenset()
    conflicts: tuple[str, ...] = ()
    absolute_ratio_floor: float = 0.10
    minimum_new_units: int = 3


def _text_values(value: object) -> list[str]:
    values = value if isinstance(value, list) else [value]
    return [item.strip() for item in values if isinstance(item, str) and item.strip()]


def _active_baseline(path: Path) -> tuple[dict[str, Any], str | None]:
    try:
        artifact = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, None
    if not isinstance(artifact, dict) or artifact.get("status") != "active":
        return {}, None
    data = artifact.get("data")
    if not isinstance(data, dict):
        return {}, None
    version = artifact.get("version")
    return data, f"prose_baseline:{version}" if version is not None else "prose_baseline"


def _authorized_beats(rules: list[str], structured: object) -> frozenset[str]:
    beats: set[str] = set()
    if isinstance(structured, dict):
        values = structured.get("authorized_short_beats", [])
        if isinstance(values, list):
            beats.update(str(item) for item in values if str(item) in KNOWN_BEATS)
    for rule in rules:
        lowered = rule.casefold()
        if "短句" not in rule and "留白" not in rule and "short sentence" not in lowered:
            continue
        for beat, markers in BEAT_RULES.items():
            if any(marker.casefold() in lowered for marker in markers):
                beats.add(beat)
    return frozenset(beats)


def load_prose_validation_policy(project_path: Path) -> ProseValidationPolicy:
    project_path = Path(project_path)
    sources: list[str] = []
    rules: list[str] = []

    profile_path = project_path / "style-profile.md"
    try:
        profile = profile_path.read_text(encoding="utf-8").strip()
    except OSError:
        profile = ""
    if profile:
        sources.append("style-profile")
        rules.append(profile)

    baseline, baseline_source = _active_baseline(
        project_path / "learning" / "prose_baseline.json"
    )
    if baseline_source:
        sources.append(baseline_source)
    for field in STYLE_FIELDS:
        rules.extend(_text_values(baseline.get(field)))

    joined = "\n".join(rules).casefold()
    permits_all = any(marker.casefold() in joined for marker in ABSOLUTE_SHORT_PERMISSION)
    prohibits_all = any(marker.casefold() in joined for marker in ABSOLUTE_SHORT_PROHIBITION)
    conflicts = ("style_policy_conflict",) if permits_all and prohibits_all else ()
    beats = frozenset() if conflicts else _authorized_beats(
        rules, baseline.get("validation_policy")
    )
    return ProseValidationPolicy(
        source_ids=tuple(sources),
        authorized_short_beats=beats,
        conflicts=conflicts,
    )


def infer_narrative_beat_tags(context: dict[str, Any]) -> frozenset[str]:
    tags: set[str] = set()
    if context.get("knowledge_changed") or context.get("reveals"):
        tags.add("information_reveal")
    if context.get("relationship_changed"):
        tags.add("relationship_change")
    if context.get("payoffs") or context.get("resolved_promises"):
        tags.add("suspense_turn")
    scenes = context.get("scenes", [])
    if isinstance(scenes, list) and any(
        isinstance(scene, dict) and scene.get("state_changes") for scene in scenes
    ):
        tags.add("emotion_shift")
    return frozenset(tags)
