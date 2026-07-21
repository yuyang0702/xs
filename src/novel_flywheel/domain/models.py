from pydantic import BaseModel, Field


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
    tools: list[ToolDefinition] = Field(default_factory=list)


class ModelResponse(BaseModel):
    text: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    finish_reason: str | None = None
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    raw_request_id: str | None = None
    provider_state: dict = Field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens
