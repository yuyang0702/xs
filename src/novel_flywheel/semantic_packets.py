from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from novel_flywheel.storage import atomic_write


PACKET_PROTOCOL_VERSION = 1
_T = TypeVar("_T")
_SHA256 = re.compile(r"[0-9a-f]{64}")


def canonical_sha256(value: object) -> str:
    """Hash JSON-compatible protocol data independently of presentation order."""
    return hashlib.sha256(json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


class SemanticPacketContract(BaseModel):
    """Immutable ownership envelope for one resumable model subtask.

    Context IDs are deliberately separate from owned IDs.  They may be shown
    to the model for continuity, but can never be promoted as this packet's
    output ownership.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[PACKET_PROTOCOL_VERSION] = PACKET_PROTOCOL_VERSION
    task_kind: str = Field(min_length=1)
    authority_sha256: str
    parent_packet_id: str = ""
    depth: int = Field(default=0, ge=0, le=32)
    owned_event_ids: tuple[str, ...] = Field(min_length=1)
    context_event_ids: tuple[str, ...] = ()
    segment_numbers: tuple[int, ...] = ()
    predecessor_sha256: str = ""

    @field_validator("authority_sha256", "predecessor_sha256")
    @classmethod
    def validate_digest(cls, value: str) -> str:
        if value and not _SHA256.fullmatch(value):
            raise ValueError("packet digests must be lowercase SHA-256 values")
        return value

    @field_validator("owned_event_ids", "context_event_ids")
    @classmethod
    def normalize_event_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(str(value or "").strip().upper() for value in values)
        if any(not value for value in normalized):
            raise ValueError("packet event IDs must not be empty")
        if len(normalized) != len(set(normalized)):
            raise ValueError("packet event IDs must not contain duplicates")
        return normalized

    @model_validator(mode="after")
    def validate_ownership(self) -> "SemanticPacketContract":
        if set(self.owned_event_ids) & set(self.context_event_ids):
            raise ValueError("context IDs must not claim packet ownership")
        if self.segment_numbers and any(value <= 0 for value in self.segment_numbers):
            raise ValueError("segment numbers must be positive")
        return self

    @property
    def packet_id(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


class ValidatedPacketCheckpoint(BaseModel):
    """Atomic, content-addressed leaf or reduction result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[PACKET_PROTOCOL_VERSION] = PACKET_PROTOCOL_VERSION
    status: Literal["validated"] = "validated"
    contract: SemanticPacketContract
    output_sha256: str
    payload: dict[str, Any]

    @field_validator("output_sha256")
    @classmethod
    def validate_output_digest(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("packet output digest must be lowercase SHA-256")
        return value

    @model_validator(mode="after")
    def validate_payload_hash(self) -> "ValidatedPacketCheckpoint":
        if canonical_sha256(self.payload) != self.output_sha256:
            raise ValueError("packet checkpoint payload hash does not match")
        return self


class CausalPacketPayload(BaseModel):
    """Provider-independent causal-chain packet shape.

    Global narrative fields stay intentionally permissive for compatibility;
    ordered ownership and cycle closure are validated separately by Runtime.
    """

    model_config = ConfigDict(extra="allow")

    core_goal: Any = ""
    opening: Any = Field(default_factory=dict)
    cycles: list[dict[str, Any]] = Field(default_factory=list)
    accidents: list[Any] = Field(default_factory=list)
    reversal: Any = Field(default_factory=dict)
    ending: Any = ""
    question_chain: Any = Field(default_factory=list)
    relationship_arc: Any = Field(default_factory=list)
    covered_event_ids: list[str] = Field(default_factory=list)

    @field_validator("covered_event_ids")
    @classmethod
    def normalize_coverage(cls, values: list[str]) -> list[str]:
        return [str(value or "").strip().upper() for value in values]


def normalize_causal_packet_payload(
    value: object,
    *,
    expected_event_ids: Sequence[str],
    owns_opening: bool,
    owns_ending: bool,
) -> dict[str, Any] | None:
    """Validate stable packet invariants without constraining creative wording."""

    def has_value(item: object) -> bool:
        if item is None:
            return False
        if isinstance(item, str):
            return bool(item.strip())
        if isinstance(item, (list, dict, tuple, set)):
            return bool(item)
        return True

    try:
        parsed = CausalPacketPayload.model_validate(value)
    except (TypeError, ValueError):
        return None
    unsafe_control_terms = (
        "skip", "override", "authorize", "operation", "patch",
        "tool_call", "machine_control", "bypass", "promote",
    )
    if any(
        any(term in re.sub(r"[^a-z0-9]+", "_", str(key).casefold())
            for term in unsafe_control_terms)
        for key in (parsed.model_extra or {})
    ):
        return None
    packet = parsed.model_dump(mode="python")
    expected = [str(event_id or "").strip().upper() for event_id in expected_event_ids]
    if packet.get("covered_event_ids") != expected:
        return None
    cycles = packet.get("cycles")
    if not isinstance(cycles, list) or not cycles:
        return None
    if not all(
        isinstance(item, dict)
        and all(has_value(item.get(key)) for key in (
            "obstacle", "effort", "result", "state_change",
        ))
        for item in cycles
    ):
        return None
    if not owns_opening and (
        has_value(packet.get("core_goal")) or has_value(packet.get("opening"))
    ):
        return None
    if not owns_ending and has_value(packet.get("ending")):
        return None
    return packet


def semantic_bisect(
    units: Sequence[_T], *, boundary_keys: Sequence[object] | None = None,
) -> tuple[tuple[_T, ...], tuple[_T, ...]]:
    """Bisect contiguously, preferring the nearest natural semantic boundary."""
    if len(units) < 2:
        raise ValueError("an indivisible semantic unit cannot be split")
    if boundary_keys is not None and len(boundary_keys) != len(units):
        raise ValueError("boundary keys must align exactly with semantic units")
    midpoint = len(units) / 2
    candidates = (
        [
            index for index in range(1, len(units))
            if boundary_keys[index - 1] != boundary_keys[index]
        ]
        if boundary_keys is not None else []
    )
    split_at = min(
        candidates or list(range(1, len(units))),
        key=lambda index: (abs(index - midpoint), index),
    )
    return tuple(units[:split_at]), tuple(units[split_at:])


def exact_ordered_partition(
    parent: Sequence[_T], children: Sequence[Sequence[_T]],
) -> bool:
    flattened = tuple(item for child in children for item in child)
    return bool(children) and all(child for child in children) and flattened == tuple(parent)


def packet_checkpoint_path(root: Path, contract: SemanticPacketContract) -> Path:
    first = re.sub(r"[^A-Za-z0-9_.-]+", "-", contract.owned_event_ids[0])
    last = re.sub(r"[^A-Za-z0-9_.-]+", "-", contract.owned_event_ids[-1])
    return root / f"packet-{first}-{last}-{contract.packet_id[:16]}.json"


def load_validated_packet(
    root: Path,
    contract: SemanticPacketContract,
    *,
    payload_validator: Callable[[dict[str, Any]], bool] | None = None,
) -> dict[str, Any] | None:
    path = packet_checkpoint_path(root, contract)
    if not path.is_file():
        return None
    try:
        checkpoint = ValidatedPacketCheckpoint.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, TypeError, ValueError):
        return None
    if checkpoint.contract != contract:
        return None
    payload = dict(checkpoint.payload)
    if payload_validator is not None and not payload_validator(payload):
        return None
    return payload


def write_validated_packet(
    root: Path,
    contract: SemanticPacketContract,
    payload: dict[str, Any],
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    checkpoint = ValidatedPacketCheckpoint(
        contract=contract,
        output_sha256=canonical_sha256(payload),
        payload=payload,
    )
    path = packet_checkpoint_path(root, contract)
    atomic_write(path, checkpoint.model_dump_json(indent=2))
    return path
