from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
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
    route_fingerprint: str = ""


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

    def update_provider(
        self,
        provider_id: str,
        *,
        name: str,
        protocol: str,
        base_url: str,
        api_key: str | None = None,
        auth_type: str = "bearer",
        timeout_seconds: int = 180,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        current = self.db.get_provider(provider_id)
        if current is None:
            raise ValueError("provider_not_found")
        if protocol not in ADAPTERS:
            raise ValueError("unsupported_protocol")
        if not name.strip() or not base_url.startswith(("http://", "https://")):
            raise ValueError("invalid_provider")
        old_route_identity = self._provider_route_identity(current)
        self.db.save_provider(
            provider_id=provider_id,
            name=name.strip(),
            protocol=protocol,
            base_url=base_url,
            auth_type=auth_type,
            timeout_seconds=timeout_seconds,
            extra_headers=extra_headers or {},
            enabled=current["enabled"],
        )
        if api_key and api_key.strip():
            self.secrets.set(provider_id, api_key.strip())
        updated = self.db.get_provider(provider_id)
        if updated and self._provider_route_identity(updated) != old_route_identity:
            self._invalidate_provider_probes(provider_id)

    def add_model(
        self, provider_id: str, display_name: str, model_name: str,
        capabilities: dict | None = None, *,
        context_window: int | None = None,
        max_output_tokens: int | None = None,
    ) -> str:
        if self.db.get_provider(provider_id) is None:
            raise ValueError("provider_not_found")
        if not display_name.strip() or not model_name.strip():
            raise ValueError("invalid_model")
        model_id = str(uuid4())
        self.db.save_model(model_id=model_id, provider_id=provider_id,
                           display_name=display_name.strip(), model_name=model_name.strip(),
                           context_window=context_window,
                           max_output_tokens=max_output_tokens,
                           capabilities=capabilities)
        return model_id

    def update_model_capabilities(
        self, provider_id: str, model_id: str, capabilities: dict,
    ) -> dict:
        model = self.db.get_model(model_id)
        if model is None or model.get("provider_id") != provider_id:
            raise ValueError("model_not_found")
        merged = {**(model.get("capabilities") or {}), **capabilities}
        self.db.save_model(
            model_id=model_id,
            provider_id=provider_id,
            display_name=model["display_name"],
            model_name=model["model_name"],
            context_window=model.get("context_window"),
            max_output_tokens=model.get("max_output_tokens"),
            capabilities=merged,
        )
        updated = self.db.get_model(model_id)
        assert updated is not None
        return updated

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
        fingerprint = self.route_fingerprint(provider, model)
        capabilities = self._effective_capabilities(
            model.get("capabilities") or {}, fingerprint,
        )
        return ResolvedModel(
            provider_id, model_id, model["model_name"], adapter,
            capabilities, fingerprint,
        )

    @staticmethod
    def _provider_route_identity(provider: dict) -> str:
        payload = {
            "protocol": provider.get("protocol"),
            "base_url": str(provider.get("base_url") or "").rstrip("/"),
            "auth_type": provider.get("auth_type"),
            "extra_headers": provider.get("extra_headers") or {},
        }
        return hashlib.sha256(json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()

    @classmethod
    def route_fingerprint(cls, provider: dict, model: dict) -> str:
        payload = {
            "provider_route": cls._provider_route_identity(provider),
            "model_name": model.get("model_name"),
        }
        return hashlib.sha256(json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()

    @staticmethod
    def _effective_capabilities(capabilities: dict, fingerprint: str) -> dict:
        result = dict(capabilities)
        probed_route = str(result.get("capability_probe_route_fingerprint") or "")
        if not probed_route:
            # Legacy/manual capabilities remain compatible until an observed
            # route-local probe takes authority for this model.
            return result
        expires_at = str(result.get("capability_probe_expires_at") or "")
        expired = False
        if expires_at:
            try:
                expires = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                expired = expires <= datetime.now(timezone.utc)
            except ValueError:
                expired = True
        if probed_route != fingerprint or expired:
            result.update({
                "structured_output": "plain_text",
                "tool_support": "auto",
                "structured_output_qualification": "unqualified",
                "verified_business_output_characters": 0,
                "capability_probe_status": "stale",
                "capability_probe_stale_reason": (
                    "route_changed" if probed_route != fingerprint else "expired"
                ),
            })
        return result

    def _invalidate_provider_probes(self, provider_id: str) -> None:
        for model in self.db.list_models(provider_id):
            capabilities = dict(model.get("capabilities") or {})
            if not capabilities.get("capability_probe_route_fingerprint"):
                continue
            capabilities.update({
                "capability_probe_status": "stale",
                "capability_probe_stale_reason": "route_changed",
            })
            self.db.save_model(
                model_id=model["id"], provider_id=provider_id,
                display_name=model["display_name"], model_name=model["model_name"],
                context_window=model.get("context_window"),
                max_output_tokens=model.get("max_output_tokens"),
                capabilities=capabilities,
            )

    def delete_provider(self, provider_id: str) -> None:
        self.db.delete_provider(provider_id)
        self.secrets.delete(provider_id)

    def update_api_key(self, provider_id: str, api_key: str) -> None:
        if self.db.get_provider(provider_id) is None:
            raise ValueError("provider_not_found")
        if not api_key.strip():
            raise ValueError("missing_api_key")
        self.secrets.set(provider_id, api_key.strip())
