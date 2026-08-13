from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field


class StructuredOutputCapability(StrEnum):
    """Route-local structured-output behavior.

    Capabilities are deliberately configured per provider/model route.  A
    model or provider brand never implies that a third-party compatibility
    endpoint implements the vendor's native structured-output protocol.
    """

    PLAIN_TEXT = "plain_text"
    JSON_OBJECT = "json_object"
    STRICT_JSON_SCHEMA = "strict_json_schema"
    STRICT_TOOL = "strict_tool"


class StructuredOutputRequirement(StrEnum):
    PLAIN_TEXT = "plain_text"
    JSON_OBJECT = "json_object"
    STRICT = "strict"


_CAPABILITY_ALIASES = {
    "": StructuredOutputCapability.PLAIN_TEXT,
    "auto": StructuredOutputCapability.PLAIN_TEXT,
    "disabled": StructuredOutputCapability.PLAIN_TEXT,
    "none": StructuredOutputCapability.PLAIN_TEXT,
    "plain": StructuredOutputCapability.PLAIN_TEXT,
    "plain_text": StructuredOutputCapability.PLAIN_TEXT,
    "json": StructuredOutputCapability.JSON_OBJECT,
    "json_mode": StructuredOutputCapability.JSON_OBJECT,
    "json_object": StructuredOutputCapability.JSON_OBJECT,
    "schema": StructuredOutputCapability.STRICT_JSON_SCHEMA,
    "strict_schema": StructuredOutputCapability.STRICT_JSON_SCHEMA,
    "strict_json_schema": StructuredOutputCapability.STRICT_JSON_SCHEMA,
    "tool": StructuredOutputCapability.STRICT_TOOL,
    "strict_tool": StructuredOutputCapability.STRICT_TOOL,
}


def configured_structured_output_capability(
    capabilities: Mapping[str, Any] | None,
) -> StructuredOutputCapability:
    """Return only an explicitly recorded route capability.

    Missing and ``auto`` values intentionally resolve to plain text.  This is
    the safe default for third-party gateways whose advertised model name does
    not prove support for a native vendor protocol.
    """

    raw = str((capabilities or {}).get("structured_output") or "").strip().casefold()
    return _CAPABILITY_ALIASES.get(raw, StructuredOutputCapability.PLAIN_TEXT)


def capability_satisfies(
    capability: StructuredOutputCapability,
    requirement: StructuredOutputRequirement,
) -> bool:
    if requirement == StructuredOutputRequirement.PLAIN_TEXT:
        return True
    if requirement == StructuredOutputRequirement.JSON_OBJECT:
        return capability in {
            StructuredOutputCapability.JSON_OBJECT,
            StructuredOutputCapability.STRICT_JSON_SCHEMA,
            StructuredOutputCapability.STRICT_TOOL,
        }
    return capability in {
        StructuredOutputCapability.STRICT_JSON_SCHEMA,
        StructuredOutputCapability.STRICT_TOOL,
    }


class StructuredOutputCapabilityError(RuntimeError):
    def __init__(
        self,
        *,
        provider_id: str,
        model_id: str,
        capability: StructuredOutputCapability,
        requirement: StructuredOutputRequirement,
    ) -> None:
        super().__init__(
            "configured route cannot satisfy structured output requirement: "
            f"provider={provider_id}, model={model_id}, "
            f"capability={capability.value}, requirement={requirement.value}"
        )
        self.provider_id = provider_id
        self.model_id = model_id
        self.capability = capability
        self.requirement = requirement


class StructuredArtifactContract(BaseModel):
    """Versioned schema plus immutable Runtime-owned task identity."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, populate_by_name=True,
    )

    name: str = Field(min_length=1)
    json_schema: dict[str, Any] = Field(alias="schema")
    version: int = Field(default=1, ge=1)
    runtime_authority: dict[str, Any] = Field(default_factory=dict)

    def provider_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "strict": True,
            "schema": self.json_schema,
        }

    def schema_sha256(self) -> str:
        encoded = json.dumps(
            self.json_schema,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def required_top_level_fields(self) -> tuple[str, ...]:
        required = self.json_schema.get("required", ())
        if not isinstance(required, (list, tuple)):
            return ()
        return tuple(
            str(value) for value in required
            if isinstance(value, str) and value
        )
