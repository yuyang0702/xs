from dataclasses import dataclass, field
from typing import Callable
from uuid import uuid4

from novel_flywheel.db import Database
from novel_flywheel.providers.anthropic import AnthropicAdapter
from novel_flywheel.providers.base import ProviderAdapter
from novel_flywheel.providers.openai_chat import OpenAIChatAdapter
from novel_flywheel.providers.openai_responses import OpenAIResponsesAdapter
from novel_flywheel.secrets import SecretStore


ADAPTERS: dict[str, Callable[..., ProviderAdapter]] = {
    "openai-chat": OpenAIChatAdapter,
    "openai-responses": OpenAIResponsesAdapter,
    "anthropic": AnthropicAdapter,
}


@dataclass(frozen=True)
class ResolvedModel:
    provider_id: str
    model_id: str
    model_name: str
    adapter: ProviderAdapter
    capabilities: dict = field(default_factory=dict)


class ProviderRegistry:
    def __init__(self, db: Database, secrets: SecretStore) -> None:
        self.db = db
        self.secrets = secrets

    def add_provider(
        self,
        *,
        name: str,
        protocol: str,
        base_url: str,
        api_key: str,
        auth_type: str = "bearer",
        timeout_seconds: int = 180,
        extra_headers: dict[str, str] | None = None,
        provider_id: str | None = None,
    ) -> str:
        if protocol not in ADAPTERS:
            raise ValueError("unsupported_protocol")
        if not name.strip() or not base_url.startswith(("http://", "https://")):
            raise ValueError("invalid_provider")
        provider_id = provider_id or str(uuid4())
        self.db.save_provider(provider_id=provider_id, name=name.strip(), protocol=protocol,
                              base_url=base_url, auth_type=auth_type, timeout_seconds=timeout_seconds,
                              extra_headers=extra_headers or {})
        self.secrets.set(provider_id, api_key)
        return provider_id

    def add_model(self, provider_id: str, display_name: str, model_name: str,
                  capabilities: dict | None = None) -> str:
        if self.db.get_provider(provider_id) is None:
            raise ValueError("provider_not_found")
        if not display_name.strip() or not model_name.strip():
            raise ValueError("invalid_model")
        model_id = str(uuid4())
        self.db.save_model(model_id=model_id, provider_id=provider_id,
                           display_name=display_name.strip(), model_name=model_name.strip(),
                           capabilities=capabilities)
        return model_id

    def resolve(self, provider_id: str, model_id: str) -> ResolvedModel:
        provider = self.db.get_provider(provider_id)
        model = self.db.get_model(model_id)
        secret = self.secrets.get(provider_id)
        if provider is None or not provider["enabled"]:
            raise ValueError("provider_not_found")
        if model is None or model["provider_id"] != provider_id:
            raise ValueError("model_not_found")
        if not secret:
            raise ValueError("missing_api_key")
        adapter = ADAPTERS[provider["protocol"]](provider["base_url"], secret,
                                                  provider["extra_headers"], provider["timeout_seconds"],
                                                  auth_type=provider["auth_type"])
        return ResolvedModel(provider_id, model_id, model["model_name"], adapter, model["capabilities"])

    def delete_provider(self, provider_id: str) -> None:
        self.db.delete_provider(provider_id)
        self.secrets.delete(provider_id)
