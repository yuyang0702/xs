from typing import Protocol

from novel_flywheel.domain.models import ModelRequest, ModelResponse


class ProviderAdapter(Protocol):
    async def complete(self, request: ModelRequest) -> ModelResponse: ...

