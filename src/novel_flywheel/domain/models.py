from pydantic import BaseModel, Field


class Message(BaseModel):
    role: str
    content: str


class ModelRequest(BaseModel):
    model: str
    messages: list[Message]
    temperature: float | None = None
    max_output_tokens: int | None = None
    response_schema: dict | None = None


class ModelResponse(BaseModel):
    text: str
    finish_reason: str | None = None
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    raw_request_id: str | None = None

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

