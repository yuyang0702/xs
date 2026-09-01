from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Message(BaseModel):
    role: str
    content: str


class ToolDefinition(BaseModel):
    name: str
    description: str
    input_schema: dict


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict


class ModelRequest(BaseModel):
    model: str
    messages: list[Message]
    temperature: float | None = None
    max_output_tokens: int | None = None
    response_schema: dict | None = None
    response_format: str | None = None
    tools: list[ToolDefinition] = Field(default_factory=list)
    required_tool: str | None = None
    reasoning_directive: Literal[
        "current_provider_default", "disable_reasoning"
    ] = "current_provider_default"
    stage_role: str = "NORMAL"


class ProviderOutputShapeV1(BaseModel):
    """Privacy-safe provider output topology captured before normalization."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, populate_by_name=True,
    )

    schema_name: Literal["ProviderOutputShapeV1"] = Field(
        default="ProviderOutputShapeV1",
        alias="schema",
        serialization_alias="schema",
    )
    version: Literal[1] = 1
    provider_family: str = Field(min_length=1, max_length=64)
    protocol: str = Field(min_length=1, max_length=64)
    finish_reason: str | None = Field(default=None, max_length=64)
    output_tokens: int = Field(default=0, ge=0)
    content_block_count: int = Field(ge=0)
    content_block_type_sequence: tuple[str, ...]
    unknown_block_type_sha256s: tuple[str, ...] = ()
    text_block_count: int = Field(ge=0)
    provider_visible_text_chars: int = Field(ge=0)
    tool_call_count: int = Field(ge=0)
    reasoning_block_count: int = Field(ge=0)
    unknown_block_count: int = Field(ge=0)
    transport_complete: bool
    normalized_visible_text_chars: int = Field(ge=0)
    normalized_tool_call_count: int = Field(ge=0)
    adapter_projection_status: Literal["exact", "changed", "unavailable"]
    raw_text_omitted: Literal[True] = True
    raw_tool_arguments_omitted: Literal[True] = True
    raw_provider_content_omitted: Literal[True] = True
    raw_headers_omitted: Literal[True] = True
    shape_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_shape_counts(self) -> "ProviderOutputShapeV1":
        if self.content_block_count != len(self.content_block_type_sequence):
            raise ValueError("provider output block count does not match sequence")
        if self.unknown_block_count != len(self.unknown_block_type_sha256s):
            raise ValueError("provider output unknown count does not match hashes")
        classified = (
            self.text_block_count
            + self.tool_call_count
            + self.reasoning_block_count
            + self.unknown_block_count
        )
        if classified > self.content_block_count:
            raise ValueError("provider output classified blocks overlap")
        if self.adapter_projection_status == "exact" and (
            self.provider_visible_text_chars
            != self.normalized_visible_text_chars
            or self.tool_call_count != self.normalized_tool_call_count
        ):
            raise ValueError("exact provider projection counts do not match")
        return self


class ModelResponse(BaseModel):
    text: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    finish_reason: str | None = None
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    raw_request_id: str | None = None
    provider_state: dict = Field(default_factory=dict)
    output_shape: ProviderOutputShapeV1 | None = None

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens
