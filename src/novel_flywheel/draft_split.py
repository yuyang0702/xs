from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import re


STALE_TARGET = re.compile(
    r"(?:目标约|本次唯一字数目标\s*[：:]\s*约?)\s*\d+\s*个正文汉字"
)
MAX_DRAFT_TASK_DEPTH = 2


@dataclass(frozen=True)
class DraftTaskContract:
    authority_sha256: str
    task_id: str
    parent_task_id: str
    depth: int
    target_han: int
    event_ids: tuple[str, ...]
    scope: str
    entry_state: str
    exit_requirement: str
    previous_sibling_sha256: str = ""

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[0-9a-f]{64}", self.authority_sha256):
            raise ValueError("authority_sha256 must be a lowercase SHA-256 digest")
        if not self.task_id.strip() or not 0 <= self.depth <= MAX_DRAFT_TASK_DEPTH:
            raise ValueError("task_id and depth must identify the current task")
        if self.target_han <= 0:
            raise ValueError("target_han must be positive")
        if len(set(self.event_ids)) != len(self.event_ids):
            raise ValueError("event_ids must not contain duplicates")
        if not self.scope.strip():
            raise ValueError("scope must describe the owned causal work")
        if self.previous_sibling_sha256 and not re.fullmatch(
            r"[0-9a-f]{64}", self.previous_sibling_sha256
        ):
            raise ValueError("previous_sibling_sha256 must be empty or a SHA-256 digest")


def render_draft_task_prompt(authority: str, contract: DraftTaskContract) -> str:
    """Render a task from immutable authority without inheriting a parent's target."""
    if STALE_TARGET.search(authority):
        raise ValueError("draft authority contains a stale numeric target")
    payload = json.dumps(asdict(contract), ensure_ascii=False, separators=(",", ":"))
    minimum_han, maximum_han = target_bounds(contract.target_han)
    return (
        "正文子任务执行契约。只执行 CURRENT_TASK_CONTRACT，不得扩大或缩小事件范围。\n"
        f"本次唯一字数目标：约 {contract.target_han} 个正文汉字。\n"
        f"本次允许完整场景范围：{minimum_han}-{maximum_han} 个正文汉字。\n"
        "不要提问。只返回可发布的小说正文，不要标题、说明、总结或状态清单。\n\n"
        f"CURRENT_TASK_CONTRACT:\n{payload}\n\n"
        f"IMMUTABLE_AUTHORITY:\n{authority.strip()}"
    )


def exact_event_partition(
    parent: tuple[str, ...], first: tuple[str, ...], second: tuple[str, ...]
) -> bool:
    return bool(first and second) and first + second == parent


def target_bounds(target: int) -> tuple[int, int]:
    """Return the one deterministic Han-character range used at every task level."""
    if target <= 0:
        raise ValueError("target must be positive")
    return int(target * 0.45), int(target * 1.45)


def residual_target(parent_target: int, accepted_first_han: int, floor: int = 400) -> int:
    if parent_target <= 0 or accepted_first_han < 0 or floor <= 0:
        raise ValueError("targets and accepted length must be valid")
    return max(floor, parent_target - accepted_first_han)


def _exact_prose_evidence(prose: str, value: object, field: str) -> str:
    evidence = str(value or "").strip()
    if not evidence or evidence not in prose:
        raise ValueError(f"semantic receipt {field} evidence is not bound to prose")
    return evidence


def validate_semantic_receipt(
    contract: DraftTaskContract,
    prose: str,
    receipt: object,
) -> dict:
    """Validate an independent semantic verdict against immutable prose bytes."""
    if not isinstance(receipt, dict):
        raise ValueError("semantic receipt must be a JSON object")
    if receipt.get("authority_sha256") != contract.authority_sha256:
        raise ValueError("semantic receipt authority hash is stale")
    if receipt.get("task_id") != contract.task_id:
        raise ValueError("semantic receipt task identity is stale")
    prose_sha256 = hashlib.sha256(prose.encode("utf-8")).hexdigest()
    if receipt.get("prose_sha256") != prose_sha256:
        raise ValueError("semantic receipt prose hash is stale")
    event_receipts = receipt.get("event_receipts")
    if not isinstance(event_receipts, list) or any(
        not isinstance(item, dict) for item in event_receipts
    ):
        raise ValueError("semantic receipt event evidence is invalid")
    returned_ids = [str(item.get("event_id") or "") for item in event_receipts]
    if returned_ids != list(contract.event_ids):
        raise ValueError("semantic receipt event coverage is incomplete or out of order")
    normalized_events = [
        {
            "event_id": event_id,
            "evidence": _exact_prose_evidence(
                prose, item.get("evidence"), f"event {event_id}",
            ),
        }
        for event_id, item in zip(returned_ids, event_receipts)
    ]
    normalized_states = {}
    for field in ("entry", "exit"):
        state = receipt.get(field)
        if not isinstance(state, dict) or state.get("satisfied") is not True:
            raise ValueError(f"semantic receipt {field} state is not satisfied")
        normalized_states[field] = {
            "satisfied": True,
            "evidence": _exact_prose_evidence(
                prose, state.get("evidence"), field,
            ),
        }
    outside = receipt.get("outside_event_ids")
    if outside != []:
        raise ValueError("semantic receipt outside event ownership is not empty")
    if receipt.get("causal_order_valid") is not True:
        raise ValueError("semantic receipt causal order is invalid")
    summary = str(receipt.get("summary") or "").strip()
    if not summary:
        raise ValueError("semantic receipt summary is missing")
    return {
        **receipt,
        "prose_sha256": prose_sha256,
        "event_receipts": normalized_events,
        **normalized_states,
        "outside_event_ids": [],
        "causal_order_valid": True,
        "summary": summary[:500],
    }


def validate_whole_draft_receipt(
    authority_sha256: str,
    draft: str,
    segments: list[str],
    event_ids: list[str],
    receipt: object,
) -> dict:
    """Fail closed unless a global verdict covers exact segment and event manifests."""
    if not isinstance(receipt, dict):
        raise ValueError("whole draft receipt must be a JSON object")
    if receipt.get("authority_sha256") != authority_sha256:
        raise ValueError("whole draft authority hash is stale")
    draft_sha256 = hashlib.sha256(draft.encode("utf-8")).hexdigest()
    if receipt.get("draft_sha256") != draft_sha256:
        raise ValueError("whole draft hash is stale")
    segment_sha256 = [
        hashlib.sha256(segment.encode("utf-8")).hexdigest() for segment in segments
    ]
    if receipt.get("segment_sha256") != segment_sha256:
        raise ValueError("whole draft segment manifest is incomplete")
    if receipt.get("event_ids") != event_ids:
        raise ValueError("whole draft event manifest is incomplete")
    for field in ("missing_event_ids", "duplicate_event_ids", "out_of_order_event_ids"):
        if receipt.get(field) != []:
            raise ValueError(f"whole draft {field} is not empty")
    for field in (
        "causal_order_valid", "continuity_valid", "ending_valid", "commitments_valid",
    ):
        if receipt.get(field) is not True:
            raise ValueError(f"whole draft {field} is not satisfied")
    evidence = receipt.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        raise ValueError("whole draft evidence is missing")
    normalized_evidence = []
    for item in evidence:
        if not isinstance(item, dict):
            raise ValueError("whole draft evidence is invalid")
        normalized_evidence.append({
            "kind": str(item.get("kind") or "global")[:80],
            "excerpt": _exact_prose_evidence(
                draft, item.get("excerpt"), "whole draft",
            ),
        })
    summary = str(receipt.get("summary") or "").strip()
    if not summary:
        raise ValueError("whole draft summary is missing")
    return {
        **receipt,
        "draft_sha256": draft_sha256,
        "segment_sha256": segment_sha256,
        "event_ids": list(event_ids),
        "evidence": normalized_evidence,
        "summary": summary[:800],
    }
