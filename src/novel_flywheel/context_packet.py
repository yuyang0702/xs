from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import re
import unicodedata
from typing import Any

from novel_flywheel.context_policy import estimate_input_tokens


_HARD_MARKERS = (
    "必须", "不得", "不能", "不可", "禁止", "只允许", "务必",
    "must", "never", "do not", "cannot", "required", "forbidden",
)
_KNOWN_INVARIANT_MARKERS = (
    "视角", "叙述人称", "viewpoint", "point of view", "pov",
    "确认结局", "confirmed ending", "知识边界", "认知边界",
    "knowledge boundary", "locked fact", "锁定事实",
)
_HARD_SECTION_MARKERS = (
    "hard rule", "hard rules", "mandatory", "requirements", "locked fact",
    "locked facts", "confirmed fact", "confirmed facts", "must include",
    "must avoid", "强制规则", "硬性规则", "锁定事实", "确认事实", "必须包含",
    "必须避免",
)
_EXAMPLE_MARKERS = (
    "example", "examples", "示例", "改写前", "改写后",
)
_EXAMPLE_LINE = re.compile(
    r"^(?:example|examples|示例|改写前|改写后)\s*[:：]",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class MandatoryRule:
    rule_id: str
    text: str
    sources: tuple[str, ...]


@dataclass(frozen=True)
class ContextLayer:
    name: str
    characters: int
    estimated_tokens: int


@dataclass(frozen=True)
class StageContextPacket:
    stage: str
    current_contract: dict[str, Any]
    mandatory_rules: tuple[MandatoryRule, ...]
    required_rule_ids: tuple[str, ...]
    relevant_context: str
    global_skeleton: str
    advisory: str
    source_hashes: dict[str, str]
    metrics: dict[str, Any]


def _normalize_rule(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold().strip()
    value = re.sub(r"^[#>*+\-\d.)\s]+", "", value)
    return re.sub(r"\s+", " ", value)


def _rule_id(normalized: str) -> str:
    return "RULE-" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16].upper()


def _source_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _rule_lines(value: str) -> list[str]:
    result = []
    in_example_section = False
    example_level = 0
    in_hard_section = False
    hard_level = 0
    for line in str(value or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading:
            level = len(heading.group(1))
            title = heading.group(2).casefold()
            if any(marker in title for marker in _EXAMPLE_MARKERS):
                in_example_section = True
                example_level = level
                continue
            if in_example_section and level <= example_level:
                in_example_section = False
            if any(marker in title for marker in _HARD_SECTION_MARKERS):
                in_hard_section = True
                hard_level = level
                continue
            if in_hard_section and level <= hard_level:
                in_hard_section = False
        lowered = stripped.casefold()
        if in_example_section or _EXAMPLE_LINE.match(lowered):
            continue
        stripped = re.sub(r"^[#>*+\-\s]+", "", stripped).strip()
        clauses = [
            clause.strip()
            for clause in re.split(r"[;；]+|(?<=[。！？!?])\s*", stripped)
            if clause.strip()
        ]
        for clause in clauses:
            clause_lowered = clause.casefold()
            if in_hard_section or any(
                marker in clause_lowered
                for marker in (*_HARD_MARKERS, *_KNOWN_INVARIANT_MARKERS)
            ):
                result.append(clause)
    return result


def extract_mandatory_rules(
    constraints: str,
    skill_prompt: str,
    *,
    stage: str,
    explicit_invariants: dict[str, Any] | None = None,
) -> tuple[tuple[MandatoryRule, ...], int]:
    del stage  # applicability is expressed by the caller's selected source packet
    entries: list[tuple[str, str]] = []
    explicit_values = []
    explicit_duplicates = 0
    for key, value in (explicit_invariants or {}).items():
        if value is None or value == "":
            continue
        rendered = (
            json.dumps(value, ensure_ascii=False, sort_keys=True)
            if isinstance(value, (dict, list, tuple))
            else str(value).strip()
        )
        entries.append(("explicit_invariant", f"{key}: {rendered}"))
        explicit_values.append(str(rendered).casefold())

    for source, content in (("constraints", constraints), ("skill", skill_prompt)):
        for line in _rule_lines(content):
            lowered = line.casefold()
            if any(value and value in lowered for value in explicit_values):
                explicit_duplicates += 1
                continue
            entries.append((source, line))

    ordered: list[str] = []
    by_normalized: dict[str, MandatoryRule] = {}
    duplicates = explicit_duplicates
    for source, text in entries:
        normalized = _normalize_rule(text)
        if not normalized:
            continue
        existing = by_normalized.get(normalized)
        if existing is not None:
            duplicates += 1
            if source not in existing.sources:
                by_normalized[normalized] = MandatoryRule(
                    rule_id=existing.rule_id,
                    text=existing.text,
                    sources=(*existing.sources, source),
                )
            continue
        ordered.append(normalized)
        by_normalized[normalized] = MandatoryRule(
            rule_id=_rule_id(normalized), text=text, sources=(source,),
        )
    return tuple(by_normalized[key] for key in ordered), duplicates


def _advisory_excerpt(value: str, limit: int) -> str:
    text = str(value or "").strip()
    if limit <= 0 or not text:
        return ""
    if len(text) <= limit:
        return text
    paragraphs = [item.strip() for item in re.split(r"\n\s*\n", text) if item.strip()]
    result = ""
    for paragraph in paragraphs:
        addition = ("\n\n" if result else "") + paragraph
        if len(result) + len(addition) > limit:
            break
        result += addition
    return result or text[:limit]


def _advisory_without_mandatory_rules(
    value: str, rules: tuple[MandatoryRule, ...],
) -> str:
    normalized_rules = {_normalize_rule(rule.text) for rule in rules}
    kept = []
    for line in str(value or "").splitlines():
        normalized = _normalize_rule(line)
        if normalized and any(
            normalized == rule or rule in normalized for rule in normalized_rules
        ):
            continue
        kept.append(line)
    return "\n".join(kept)


def _contract_text(contract: dict[str, Any]) -> str:
    return json.dumps(
        contract, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )


def _rules_text(rules: tuple[MandatoryRule, ...]) -> str:
    return "\n".join(f"[{rule.rule_id}] {rule.text}" for rule in rules)


def build_stage_context_packet(
    *,
    stage: str,
    current_contract: dict[str, Any],
    constraints: str,
    skill_prompt: str,
    explicit_invariants: dict[str, Any] | None,
    relevant_context: str,
    global_skeleton: str,
    advisory: str = "",
    output_reserve: int = 0,
    advisory_max_chars: int = 4000,
) -> StageContextPacket:
    if not str(stage or "").strip():
        raise ValueError("context packet stage must not be empty")
    if not isinstance(current_contract, dict) or not current_contract:
        raise ValueError("context packet requires a current task contract")
    if not str(relevant_context or "").strip():
        raise ValueError("context packet requires relevant source context")
    if not str(global_skeleton or "").strip():
        raise ValueError("context packet requires a global story skeleton")
    rules, duplicate_count = extract_mandatory_rules(
        constraints, skill_prompt, stage=stage,
        explicit_invariants=explicit_invariants,
    )
    if not rules:
        raise ValueError("context packet contains no mandatory narrative rules")
    advisory_excerpt = _advisory_excerpt(
        _advisory_without_mandatory_rules(advisory, rules), advisory_max_chars,
    )
    layer_text = {
        "current_contract": _contract_text(current_contract),
        "mandatory_rules": _rules_text(rules),
        "relevant_context": str(relevant_context).strip(),
        "global_skeleton": str(global_skeleton).strip(),
        "advisory": advisory_excerpt,
    }
    layers = {
        name: asdict(ContextLayer(
            name=name,
            characters=len(content),
            estimated_tokens=estimate_input_tokens(content),
        ))
        for name, content in layer_text.items()
    }
    metrics = {
        "layers": layers,
        "total_input_tokens": sum(item["estimated_tokens"] for item in layers.values()),
        "output_reserve_tokens": max(0, int(output_reserve or 0)),
        "removed_duplicate_rules": duplicate_count,
        "filtered_advisory_characters": max(0, len(str(advisory or "")) - len(advisory_excerpt)),
    }
    return StageContextPacket(
        stage=str(stage).strip(),
        current_contract=dict(current_contract),
        mandatory_rules=rules,
        required_rule_ids=tuple(rule.rule_id for rule in rules),
        relevant_context=str(relevant_context).strip(),
        global_skeleton=str(global_skeleton).strip(),
        advisory=advisory_excerpt,
        source_hashes={
            "constraints": _source_hash(str(constraints or "")),
            "skill_prompt": _source_hash(str(skill_prompt or "")),
            "relevant_context": _source_hash(str(relevant_context).strip()),
            "global_skeleton": _source_hash(str(global_skeleton).strip()),
        },
        metrics=metrics,
    )


def render_stage_context_packet(packet: StageContextPacket) -> str:
    sections = [
        "CURRENT_TASK_CONTRACT:\n" + _contract_text(packet.current_contract),
        "MANDATORY_NARRATIVE_RULES:\n" + _rules_text(packet.mandatory_rules),
        "RELEVANT_SOURCE_CONTEXT:\n" + packet.relevant_context,
        "GLOBAL_STORY_SKELETON:\n" + packet.global_skeleton,
    ]
    if packet.advisory:
        sections.append("ADVISORY_CONTEXT:\n" + packet.advisory)
    sections.append("CONTEXT_SOURCE_HASHES:\n" + json.dumps(
        packet.source_hashes, ensure_ascii=False, sort_keys=True,
    ))
    return "\n\n".join(sections)


def render_stage_system_context(packet: StageContextPacket) -> str:
    """Render non-user layers while binding the unchanged user payload by hash."""
    sections = [
        "CURRENT_TASK_ENVELOPE:\n" + _contract_text(packet.current_contract),
        "MANDATORY_NARRATIVE_RULES:\n" + _rules_text(packet.mandatory_rules),
        "GLOBAL_STORY_SKELETON:\n" + packet.global_skeleton,
    ]
    if packet.advisory:
        sections.append("ADVISORY_CONTEXT:\n" + packet.advisory)
    sections.extend([
        "CURRENT_USER_PAYLOAD_SHA256:\n" + packet.source_hashes["relevant_context"],
        "CONTEXT_SOURCE_HASHES:\n" + json.dumps(
            packet.source_hashes, ensure_ascii=False, sort_keys=True,
        ),
    ])
    return "\n\n".join(sections)


def validate_rule_coverage(packet: StageContextPacket) -> list[dict]:
    included = {rule.rule_id for rule in packet.mandatory_rules}
    return [
        {
            "code": "missing_mandatory_rule",
            "rule_id": rule_id,
            "message": "模型上下文缺少强制叙事规则",
        }
        for rule_id in packet.required_rule_ids
        if rule_id not in included
    ]


def context_packet_sha256(packet: StageContextPacket) -> str:
    payload = {
        "stage": packet.stage,
        "current_contract": packet.current_contract,
        "mandatory_rules": [asdict(rule) for rule in packet.mandatory_rules],
        "required_rule_ids": packet.required_rule_ids,
        "relevant_context": packet.relevant_context,
        "global_skeleton": packet.global_skeleton,
        "source_hashes": packet.source_hashes,
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
