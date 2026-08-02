import json
import math
import re
from typing import Any


OUTPUT_LIMIT_REASONS = {
    "length", "max_output_tokens", "max_tokens", "model_length",
}
INVALID_TERMINAL_REASONS = {
    "incomplete", "failed", "cancelled", "canceled", "content_filter", "safety",
}
AUTO_DISCOVERY_MAX_OUTPUT_TOKENS = 65_536


def estimate_input_tokens(text: str) -> int:
    cjk = len(re.findall(r"[\u3400-\u9fff]", text))
    return cjk + math.ceil((len(text) - cjk) / 4)


def normalize_finish_reason(value: object) -> str:
    reason = str(value or "").strip().lower().replace("-", "_")
    return "max_tokens" if reason in OUTPUT_LIMIT_REASONS else reason


def output_limited(receipt: dict | None) -> bool:
    return normalize_finish_reason((receipt or {}).get("finish_reason")) == "max_tokens"


def invalid_terminal_output(receipt: dict | None) -> bool:
    return normalize_finish_reason(
        (receipt or {}).get("finish_reason")
    ) in INVALID_TERMINAL_REASONS


def adaptive_output_budget(
    stage: str,
    *,
    expected_output_characters: int | None = None,
    input_tokens: int = 0,
    context_window: int | None = None,
    declared_output_ceiling: int | None = None,
) -> int | None:
    """Choose headroom for quality; this is not a content or cost limit."""
    baseline = stage_output_budget(stage, expected_output_characters)
    if baseline is None:
        return None
    desired = baseline
    if expected_output_characters is not None:
        expected = estimate_input_tokens("汉" * max(0, expected_output_characters))
        desired = max(baseline, math.ceil(expected * 1.75) + 1024)
    ceiling = declared_output_ceiling or AUTO_DISCOVERY_MAX_OUTPUT_TOKENS
    if context_window:
        ceiling = min(ceiling, max(1, context_window - input_tokens - 2048))
    return min(desired, ceiling)


def expanded_output_budget(
    current: int | None,
    *,
    input_tokens: int = 0,
    context_window: int | None = None,
    declared_output_ceiling: int | None = None,
) -> int | None:
    if current is None:
        return None
    ceiling = declared_output_ceiling or AUTO_DISCOVERY_MAX_OUTPUT_TOKENS
    if context_window:
        ceiling = min(ceiling, max(1, context_window - input_tokens - 2048))
    return min(ceiling, max(current + 1024, current * 2))


def _json(value: Any, limit: int) -> str:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return text if len(text) <= limit else text[:limit] + "..."


def next_retry_action(*, failure_kind: str, attempt: int,
                      current_limit: int, provider_limit: int) -> dict:
    if failure_kind == "invalid_json":
        return {"action": "schema_repair", "next_limit": min(current_limit, 4096)}
    if failure_kind == "output_limit" and current_limit < provider_limit:
        return {"action": "retry_larger", "next_limit": provider_limit}
    if failure_kind == "output_limit":
        return {"action": "split", "next_limit": current_limit}
    if attempt == 1:
        return {"action": "fallback", "next_limit": current_limit}
    return {"action": "stop", "next_limit": current_limit}


def patch_output_budget(allowed_characters: int, provider_limit: int) -> int:
    desired = max(512, math.ceil(max(0, allowed_characters) * 1.35) + 256)
    return min(max(1, provider_limit), desired)


def schema_repair_prompt(malformed_output: str, schema_id: str) -> str:
    return (
        f"Repair this malformed JSON as schema {schema_id}. Return one JSON object only. "
        "Preserve the supplied values; do not add prose or analysis.\n\n"
        f"MALFORMED JSON:\n{malformed_output[:12000]}"
    )


def revision_patch_context(
    *, issue: dict, target_paragraph: str, previous_paragraph: str,
    next_paragraph: str, evidence_summaries: list,
    seven_step_position: str, authoritative_facts: list,
    protected_passages: list, allowed_range: dict, word_target: int,
) -> str:
    return (
        f"ISSUE:\n{_json(issue, 1600)}\n\n"
        f"PREVIOUS POLISHED END:\n{previous_paragraph}\n\n"
        f"NEXT ORIGINAL START:\n{next_paragraph}\n\n"
        f"LINKED EVIDENCE SUMMARIES:\n{_json(evidence_summaries, 1600)}\n\n"
        f"SEVEN-STEP POSITION:\n{seven_step_position}\n\n"
        f"AUTHORITATIVE FACTS:\n{_json(authoritative_facts, 1800)}\n\n"
        f"PROTECTED PASSAGE SUMMARIES:\n{_json(protected_passages, 1200)}\n\n"
        f"ALLOWED RANGE:\n{_json(allowed_range, 400)}\n\n"
        f"WORD TARGET:\n{word_target}\n\n"
        f"MANUSCRIPT SEGMENT:\n{target_paragraph}"
    )


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
        "revision_plan": 8192,
        "final_review": 8192,
        "maintenance": 4096,
    }
    if stage != "polish":
        return fixed.get(stage)
    if source_characters is None:
        return 8192
    return min(8192, max(2048, math.ceil(source_characters * 1.35) + 512))
