from dataclasses import dataclass

from novel_flywheel.db import Database
from novel_flywheel.domain.models import Message, ModelRequest
from novel_flywheel.providers.registry import ProviderRegistry


@dataclass(frozen=True)
class ModelResult:
    text: str
    receipt: dict


class ModelGateway:
    def __init__(self, db: Database, registry: ProviderRegistry) -> None:
        self.db = db
        self.registry = registry

    async def complete(self, role: str, system: str, user: str,
                       max_output_tokens: int | None = None) -> ModelResult:
        binding = self.db.get_role_binding(role)
        if binding is None:
            raise LookupError(f"Model role is not configured: {role}")
        resolved = self.registry.resolve(binding["primary_provider_id"], binding["primary_model_id"])
        response = await resolved.adapter.complete(ModelRequest(
            model=resolved.model_name,
            messages=[Message(role="system", content=system), Message(role="user", content=user)],
            max_output_tokens=max_output_tokens,
        ))
        return ModelResult(response.text, {
            "role": role,
            "provider_id": resolved.provider_id,
            "model_id": resolved.model_id,
            "model_name": resolved.model_name,
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "request_id": response.raw_request_id,
        })
