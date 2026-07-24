import json
import math
from typing import Any


def _json(value: Any, limit: int) -> str:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return text if len(text) <= limit else text[:limit] + "..."


def polish_context(*, state: dict[str, Any], story_map: list[dict[str, Any]],
                   segment_index: int, segment_count: int, segment: str,
                   previous_tail: str, next_head: str, findings: str,
                   edit_rule: str) -> str:
    authoritative = {
        key: state.get(key, [] if key != "character_states" else {})
        for key in ("locked_facts", "confirmed_facts", "world_rules", "character_states")
    }
    return (
        f"POLISH SEGMENT {segment_index} OF {segment_count}. Return only revised prose.\n"
        f"EDIT PERMISSION: {edit_rule}\n\n"
        f"AUTHORITATIVE STORY CONTEXT:\n{_json(authoritative, 2200)}\n\n"
        f"COMPACT FULL STORY MAP:\n{_json(story_map, 1800)}\n\n"
        f"STRUCTURED FINDINGS:\n{findings[:1800]}\n\n"
        f"PREVIOUS POLISHED END:\n{previous_tail[-800:]}\n\n"
        f"NEXT ORIGINAL START:\n{next_head[:800]}\n\n"
        f"MANUSCRIPT SEGMENT:\n{segment}"
    )


def stage_output_budget(stage: str, source_characters: int | None = None) -> int | None:
    fixed = {
        "planning": 12288,
        "draft": 8192,
        "review": 4096,
        "revision_plan": 4096,
        "final_review": 8192,
        "maintenance": 4096,
    }
    if stage != "polish":
        return fixed.get(stage)
    if source_characters is None:
        return 8192
    return min(8192, max(2048, math.ceil(source_characters * 1.35) + 512))
