from __future__ import annotations

from enum import StrEnum
import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


WORKFLOW_CHECKPOINT_VERSION = 2


class NodeCheckpointStatus(StrEnum):
    GENERATED_COMPLETE = "generated_complete"
    VALIDATED = "validated"
    FAILED = "failed"
    STALE = "stale"


class CheckpointValidationStage(StrEnum):
    TRANSPORT = "transport"
    SYNTAX = "syntax"
    OWNERSHIP = "ownership"
    LOCAL_SEMANTICS = "local_semantics"
    ADJACENT_HANDOFF = "adjacent_handoff"
    WHOLE_STORY = "whole_story"
    QUALITY = "quality"
    PROMOTED = "promoted"


CHECKPOINT_STAGE_ORDER = tuple(CheckpointValidationStage)


def checkpoint_stage_rank(value: CheckpointValidationStage | str) -> int:
    stage = CheckpointValidationStage(value)
    return CHECKPOINT_STAGE_ORDER.index(stage)


def migrate_checkpoint_stage(
    version: int, status: NodeCheckpointStatus | str,
    validation_stage: CheckpointValidationStage | str | None = None,
) -> CheckpointValidationStage:
    """Map V1 lifecycle-only rows into the V2 validation DAG."""
    if validation_stage:
        return CheckpointValidationStage(validation_stage)
    lifecycle = NodeCheckpointStatus(status)
    if version <= 1 and lifecycle == NodeCheckpointStatus.VALIDATED:
        return CheckpointValidationStage.PROMOTED
    return CheckpointValidationStage.TRANSPORT


class CheckpointEnvelope(BaseModel):
    """Hash-bound node state; it is not a second story authority."""

    model_config = ConfigDict(extra="forbid")

    version: int = WORKFLOW_CHECKPOINT_VERSION
    run_id: str = Field(min_length=1)
    node_key: str = Field(min_length=1)
    authority_sha256: str
    input_sha256: str
    output_sha256: str = ""
    status: NodeCheckpointStatus
    validation_stage: CheckpointValidationStage = CheckpointValidationStage.TRANSPORT
    attempt: int = Field(default=1, ge=1)
    route_fingerprint: str = ""
    next_node: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("authority_sha256", "input_sha256", "output_sha256", "route_fingerprint")
    @classmethod
    def validate_digest(cls, value: str) -> str:
        if value and (len(value) != 64 or any(char not in "0123456789abcdef" for char in value)):
            raise ValueError("checkpoint digests must be lowercase SHA-256 values")
        return value

    @property
    def envelope_sha256(self) -> str:
        return hashlib.sha256(json.dumps(
            self.model_dump(mode="json"), ensure_ascii=False,
            sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()


def content_sha256(value: object) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()
