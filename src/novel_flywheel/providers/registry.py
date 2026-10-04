from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from typing import Callable
from urllib.parse import urlsplit
from uuid import uuid4

from novel_flywheel.db import Database
from novel_flywheel.execution_failure_architecture import (
    ProviderClientConstructionFailure,
    ProviderCredentialFailure,
    ProviderRouteFailure,
)
from novel_flywheel.providers.anthropic import AnthropicAdapter
from novel_flywheel.providers.base import ProviderAdapter
from novel_flywheel.providers.openai_chat import OpenAIChatAdapter
from novel_flywheel.providers.openai_responses import OpenAIResponsesAdapter
from novel_flywheel.providers.http import (
    SingleDispatchAttemptObserver,
    SingleDispatchTransportPolicyV1,
)
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
    provider_operator: str = ""
    protocol: str = ""
    destination: str = ""
    route_lane: str = ""


@dataclass(frozen=True)
class PublicRouteReadinessV1:
    """Secret-free route facts safe to validate before credential access."""

    provider: dict
    model: dict
    route_fingerprint: str
    protocol: str
    destination: str
    provider_operator: str


class ProviderRegistry:
    def __init__(
        self,
        db: Database,
        secrets: SecretStore,
        *,
        transport_policy: SingleDispatchTransportPolicyV1 | None = None,
        attempt_observer: SingleDispatchAttemptObserver | None = None,
        canonical_dispatch_required: bool = False,
        canonical_runtime_path_id: str = "",
        canonical_dispatch_failure_handler: Callable[[str], None] | None = None,
    ) -> None:
        self.db = db
        self.secrets = secrets
        self.transport_policy = transport_policy
        self.attempt_observer = attempt_observer
        self.canonical_dispatch_required = bool(canonical_dispatch_required)
        self.canonical_runtime_path_id = str(canonical_runtime_path_id or "")
        self.canonical_dispatch_failure_handler = canonical_dispatch_failure_handler

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

    def resolve(
        self, provider_id: str, model_id: str, *,
        role: str | None = None, lane: str | None = None,
        transport_policy: SingleDispatchTransportPolicyV1 | None = None,
    ) -> ResolvedModel:
        public = self.inspect_public_route(provider_id, model_id)
        provider = public.provider
        model = public.model
        # Validate all public route identity before crossing the credential
        # boundary.  The dedicated Full Short launcher performs its complete
        # immutable preflight before calling ``resolve``; this local ordering
        # additionally guarantees that an invalid provider/model identifier
        # cannot cause even a needless secret lookup.
        fingerprint = public.route_fingerprint
        if self.attempt_observer is not None:
            bind_route = getattr(self.attempt_observer, "bind_route", None)
            if callable(bind_route):
                bind_route(
                    role=str(role or ""), lane=str(lane or ""),
                    provider_id=provider_id, model_id=model_id,
                    route_fingerprint=fingerprint,
                )
        try:
            secret = self.secrets.get(provider_id)
        except Exception as exc:
            raise ProviderCredentialFailure(
                "credential_lookup_failed",
            ) from exc
        if not secret:
            raise ProviderCredentialFailure("missing_api_key")
        try:
            adapter = ADAPTERS[provider["protocol"]](
                provider["base_url"], secret, provider["extra_headers"],
                provider["timeout_seconds"], auth_type=provider["auth_type"],
                transport_policy=(transport_policy or self.transport_policy),
                attempt_observer=self.attempt_observer,
                canonical_dispatch_required=self.canonical_dispatch_required,
                canonical_runtime_path_id=self.canonical_runtime_path_id,
                canonical_dispatch_failure_handler=self.canonical_dispatch_failure_handler,
            )
        except Exception as exc:
            raise ProviderClientConstructionFailure() from exc
        capabilities = self._effective_capabilities(
            model.get("capabilities") or {}, fingerprint,
        )
        return ResolvedModel(
            provider_id, model_id, model["model_name"], adapter,
            capabilities, fingerprint,
            provider_operator=public.provider_operator,
            protocol=public.protocol,
            destination=public.destination,
            route_lane=str(lane or ""),
        )

    def inspect_public_route(
        self, provider_id: str, model_id: str,
    ) -> PublicRouteReadinessV1:
        """Validate public route/client configuration without reading secrets."""

        provider = self.db.get_provider(provider_id)
        model = self.db.get_model(model_id)
        if provider is None or not provider["enabled"]:
            raise ProviderRouteFailure("provider_not_found")
        if model is None or model["provider_id"] != provider_id:
            raise ProviderRouteFailure("model_not_found")
        protocol = str(provider.get("protocol") or "")
        if protocol not in ADAPTERS:
            raise ProviderRouteFailure("unsupported_protocol")
        base_url = str(provider.get("base_url") or "").rstrip("/")
        target_base = urlsplit(base_url)
        if (
            target_base.scheme not in {"http", "https"}
            or target_base.hostname is None
            or target_base.username is not None
            or target_base.password is not None
        ):
            raise ProviderRouteFailure("invalid_provider_destination")
        if protocol == "anthropic":
            path = "messages" if base_url.endswith("/v1") else "v1/messages"
        elif protocol == "openai-responses":
            path = "responses"
        else:
            path = "chat/completions"
        target = urlsplit(f"{base_url}/{path}")
        destination = (
            f"{target.scheme}://{target.hostname}:{target.port or 443}{target.path}"
        )
        official_deepseek = all((
            provider_id == "0e6a5627-5882-40df-bca5-7d98b97fdd0b",
            str(provider["name"]).strip().casefold() == "deepseek",
            destination == "https://api.deepseek.com:443/anthropic/v1/messages",
            protocol == "anthropic",
        ))
        official_volcengine_ark = all((
            destination
            == "https://ark.cn-beijing.volces.com:443/api/v3/responses",
            protocol == "openai-responses",
        ))
        return PublicRouteReadinessV1(
            provider=dict(provider), model=dict(model),
            route_fingerprint=self.route_fingerprint(provider, model),
            protocol=protocol, destination=destination,
            provider_operator=(
                "DEEPSEEK_OFFICIAL" if official_deepseek
                else "VOLCENGINE_ARK_DIRECT" if official_volcengine_ark
                else "THIRD_PARTY_RELAY_UNVERIFIED_UPSTREAM"
            ),
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
