import json
import hashlib
import math
import re
from dataclasses import asdict, dataclass
from typing import Any, Literal


OUTPUT_LIMIT_REASONS = {
    "length", "max_output_tokens", "max_tokens", "model_length",
}
INVALID_TERMINAL_REASONS = {
    "incomplete", "failed", "cancelled", "canceled", "content_filter", "safety",
}
AUTO_DISCOVERY_MAX_OUTPUT_TOKENS = 65_536


@dataclass(frozen=True)
class PolishAuthorityPacket:
    source: str
    event_ids: tuple[str, ...]
    causal_goal: str
    previous_exit: str
    next_entry: str
    character_state: dict[str, Any]
    locked_facts: tuple[Any, ...]
    ending_constraints: tuple[Any, ...]
    promises: tuple[Any, ...]
    narrative_state: dict[str, Any]
    style_rules: tuple[str, ...]
    protected_passages: tuple[dict[str, Any], ...]
    allowed_scope: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_polish_authority_packet(
    *,
    source: str,
    event_ids: list[str] | tuple[str, ...] = (),
    causal_goal: str = "",
    previous_exit: str = "",
    next_entry: str = "",
    character_state: dict[str, Any] | None = None,
    locked_facts: list[Any] | tuple[Any, ...] = (),
    ending_constraints: list[Any] | tuple[Any, ...] = (),
    promises: list[Any] | tuple[Any, ...] = (),
    narrative_state: dict[str, Any] | None = None,
    style_rules: list[str] | tuple[str, ...] = (),
    protected_passages: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    allowed_scope: dict[str, Any] | None = None,
) -> PolishAuthorityPacket:
    if not isinstance(source, str) or not source.strip():
        raise ValueError("polish authority requires the complete source segment")
    return PolishAuthorityPacket(
        source=source,
        event_ids=tuple(str(item) for item in event_ids if str(item)),
        causal_goal=str(causal_goal or ""),
        previous_exit=str(previous_exit or ""),
        next_entry=str(next_entry or ""),
        character_state=dict(character_state or {}),
        locked_facts=tuple(locked_facts),
        ending_constraints=tuple(ending_constraints),
        promises=tuple(promises),
        narrative_state=dict(narrative_state or {}),
        style_rules=tuple(str(item) for item in style_rules if str(item)),
        protected_passages=tuple(dict(item) for item in protected_passages),
        allowed_scope=dict(allowed_scope or {}),
    )


def authority_packet_sha256(packet: PolishAuthorityPacket) -> str:
    payload = json.dumps(
        packet.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def render_polish_authority_packet(
    packet: PolishAuthorityPacket,
    *,
    advisory: dict[str, Any] | None = None,
) -> str:
    sections = [
        "MINIMUM NARRATIVE AUTHORITY:",
        f"EVENT IDS:\n{json.dumps(packet.event_ids, ensure_ascii=False)}",
        f"CAUSAL GOAL:\n{packet.causal_goal}",
        f"PREVIOUS ACCEPTED EXIT:\n{packet.previous_exit}",
        f"NEXT SOURCE ENTRY:\n{packet.next_entry}",
        "CHARACTER STATE:\n" + json.dumps(packet.character_state, ensure_ascii=False),
        "LOCKED FACTS:\n" + json.dumps(packet.locked_facts, ensure_ascii=False),
        "ENDING CONSTRAINTS:\n" + json.dumps(packet.ending_constraints, ensure_ascii=False),
        "PROMISES AND PAYOFFS:\n" + json.dumps(packet.promises, ensure_ascii=False),
        "NARRATIVE STATE:\n" + json.dumps(packet.narrative_state, ensure_ascii=False),
        "PROJECT STYLE RULES:\n" + json.dumps(packet.style_rules, ensure_ascii=False),
        "PROTECTED PASSAGES:\n" + json.dumps(packet.protected_passages, ensure_ascii=False),
        "ALLOWED SCOPE:\n" + json.dumps(packet.allowed_scope, ensure_ascii=False),
    ]
    if advisory:
        sections.append("LOCAL ADVISORY FINDINGS:\n" + _json(advisory, 2400))
    sections.append(f"MANUSCRIPT SEGMENT:\n{packet.source}")
    return "\n\n".join(sections)


def classify_input_pressure(
    *,
    full_input_tokens: int,
    authority_input_tokens: int,
    output_reserve: int,
    context_window: int | None,
) -> str:
    if not context_window:
        return "full"
    if authority_input_tokens + output_reserve >= context_window * 0.80:
        return "split"
    if full_input_tokens + output_reserve >= context_window * 0.75:
        return "compact"
    return "full"


ModelFailureKind = Literal[
    "input_context_overflow",
    "output_limit",
    "transport_interrupted",
    "normal_invalid_output",
    "provider_rejection",
]


def classify_model_failure(value: object) -> ModelFailureKind:
    """Classify a failed model attempt without inferring route capacity from transport noise."""
    provider_markers = (
        "missing api key", "missing_api_key", "invalid api key", "invalid_api_key",
        "api key is missing", "authentication", "unauthorized", "forbidden",
        "http 401", "http 403", "status code 401", "status code 403",
        "invalid role binding", "model role is not configured", "role binding is invalid",
        "binding is corrupt", "provider_not_found", "provider not found",
        "model_not_found", "model not found",
    )
    input_markers = (
        "input context overflow",
        "maximum context length", "context length exceeded", "context_length_exceeded",
        "context window exceeded", "input token limit", "input tokens exceed",
        "prompt is too long", "prompt too long", "request too large",
        "request entity too large", "payload too large", "http 413", "status code 413",
    )
    transport_markers = (
        "connecterror", "connection attempts failed", "connection reset",
        "connection refused", "server disconnected", "peer closed connection",
        "incomplete chunked read", "readerror", "timeout", "timed out",
        "bad gateway", "gateway timeout", "502", "504", "524",
        "transport ended before a terminal response",
    )
    output_markers = (
        "finish_reason=max_tokens", "finish reason=max_tokens",
        "output token limit", "output limit reached", "max_output_tokens",
    )

    classifications: set[ModelFailureKind] = set()
    pending: list[object] = [value]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, dict):
            if output_limited(current):
                classifications.add("output_limit")
            text = json.dumps(current, ensure_ascii=False, default=str).lower()
            for key in ("error", "exception", "primary_error", "fallback_error"):
                nested = current.get(key)
                if nested is not None:
                    pending.append(nested)
        else:
            receipt = getattr(current, "receipt", None)
            if isinstance(receipt, dict):
                pending.append(receipt)
            text = str(current).lower()
            if isinstance(current, BaseException):
                for nested in (
                    getattr(current, "primary_error", None),
                    getattr(current, "fallback_error", None),
                    current.__cause__, current.__context__,
                ):
                    if nested is not None:
                        pending.append(nested)
        if any(marker in text for marker in provider_markers):
            classifications.add("provider_rejection")
        if any(marker in text for marker in input_markers):
            classifications.add("input_context_overflow")
        if any(marker in text for marker in transport_markers):
            classifications.add("transport_interrupted")
        if any(marker in text for marker in output_markers):
            classifications.add("output_limit")

    for kind in (
        "provider_rejection", "input_context_overflow", "transport_interrupted", "output_limit",
    ):
        if kind in classifications:
            return kind
    return "normal_invalid_output"


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


def bounded_protocol_output_budget(
    *, expected_output_characters: int | None,
    input_tokens: int = 0,
    context_window: int | None = None,
    declared_output_ceiling: int | None = None,
) -> int:
    """Reserve enough room for a closed JSON protocol without creative padding.

    Creative stages deliberately retain their larger adaptive budgets. Protocol
    receipts have a bounded schema, so reserving a stage-wide 4K/8K minimum can
    itself force a valid authority packet over the context safety line.
    """
    expected_characters = max(256, int(expected_output_characters or 0))
    # Closed receipts are dominated by short field names, hashes, identifiers,
    # booleans, and bounded evidence excerpts. Treating every expected
    # character as a CJK token recreates the creative-stage reserve and can
    # itself force an otherwise valid authority packet over the context line.
    expected_tokens = max(256, math.ceil(expected_characters * 0.55))
    desired = max(768, math.ceil(expected_tokens * 1.35) + 384)
    ceiling = declared_output_ceiling or AUTO_DISCOVERY_MAX_OUTPUT_TOKENS
    if context_window:
        ceiling = min(ceiling, max(1, context_window - input_tokens - 1024))
    return min(desired, ceiling)


def scoped_creative_output_budget(
    *, expected_output_characters: int | None,
    input_tokens: int = 0,
    context_window: int | None = None,
    declared_output_ceiling: int | None = None,
) -> int:
    """Reserve creative headroom for one already bounded semantic scope.

    A complete planning stage legitimately keeps a large stage-wide reserve.
    A targeted segment rebuild is different: its event ownership and expected
    size are already fixed, so inheriting the whole planning floor can consume
    the context window before the provider is called.  This initial reserve is
    deliberately generous and may still expand through the ordinary
    output-limit retry; it does not reduce the requested prose or planning
    scope.
    """
    expected_characters = max(512, int(expected_output_characters or 0))
    expected_tokens = estimate_input_tokens("汉" * expected_characters)
    desired = max(2_048, math.ceil(expected_tokens * 2.25) + 1_024)
    ceiling = declared_output_ceiling or AUTO_DISCOVERY_MAX_OUTPUT_TOKENS
    if context_window:
        ceiling = min(ceiling, max(1, context_window - input_tokens - 2_048))
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
