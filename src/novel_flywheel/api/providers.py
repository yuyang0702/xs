from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, model_validator

from novel_flywheel.providers.probe import CapabilityProbe, ProbeResult
from novel_flywheel.providers.registry import ProviderRegistry


router = APIRouter(prefix="/api", tags=["providers"])


class ProviderCreate(BaseModel):
    name: str = Field(min_length=1)
    protocol: Literal["openai-chat", "openai-responses", "anthropic"]
    base_url: str
    api_key: str = Field(min_length=1)
    auth_type: str = "bearer"
    timeout_seconds: int = Field(default=180, ge=5, le=1800)
    extra_headers: dict[str, str] = {}


class ProviderUpdate(BaseModel):
    name: str = Field(min_length=1)
    protocol: Literal["openai-chat", "openai-responses", "anthropic"]
    base_url: str
    api_key: str | None = None
    auth_type: str = "bearer"
    timeout_seconds: int = Field(default=180, ge=5, le=1800)
    extra_headers: dict[str, str] = {}


class ModelCreate(BaseModel):
    display_name: str = Field(min_length=1)
    model_name: str = Field(min_length=1)
    tool_support: Literal["auto", "enabled", "disabled"] = "auto"
    structured_output: Literal[
        "plain_text", "json_object", "strict_json_schema", "strict_tool",
    ] = "plain_text"
    context_window: int | None = Field(default=None, ge=1024)
    max_output_tokens: int | None = Field(default=None, ge=64)


class ModelCapabilityUpdate(BaseModel):
    tool_support: Literal["auto", "enabled", "disabled"] = "auto"
    structured_output: Literal[
        "plain_text", "json_object", "strict_json_schema", "strict_tool",
    ] = "plain_text"


class ApiKeyUpdate(BaseModel):
    api_key: str = Field(min_length=1)


def get_registry(request: Request) -> ProviderRegistry:
    return request.app.state.registry


def _public_provider(provider: dict, registry: ProviderRegistry) -> dict:
    return {
        **provider,
        "has_api_key": registry.secrets.get(provider["id"]) is not None,
        "models": registry.db.list_models(provider["id"]),
    }


@router.get("/providers")
def list_providers(registry: ProviderRegistry = Depends(get_registry)) -> list[dict]:
    return [_public_provider(provider, registry) for provider in registry.db.list_providers()]


@router.post("/providers", status_code=status.HTTP_201_CREATED)
def create_provider(payload: ProviderCreate, registry: ProviderRegistry = Depends(get_registry)) -> dict:
    try:
        provider_id = registry.add_provider(**payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": str(exc)}) from exc
    provider = registry.db.get_provider(provider_id)
    assert provider is not None
    return _public_provider(provider, registry)


@router.put("/providers/{provider_id}")
def update_provider(provider_id: str, payload: ProviderUpdate,
                    registry: ProviderRegistry = Depends(get_registry)) -> dict:
    try:
        registry.update_provider(provider_id, **payload.model_dump())
    except ValueError as exc:
        raise HTTPException(
            status_code=404 if str(exc) == "provider_not_found" else 400,
            detail={"code": str(exc)},
        ) from exc
    provider = registry.db.get_provider(provider_id)
    assert provider is not None
    return _public_provider(provider, registry)


@router.delete("/providers/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_provider(provider_id: str, registry: ProviderRegistry = Depends(get_registry)) -> None:
    registry.delete_provider(provider_id)


@router.put("/providers/{provider_id}/api-key")
def update_provider_api_key(provider_id: str, payload: ApiKeyUpdate,
                            registry: ProviderRegistry = Depends(get_registry)) -> dict:
    try:
        registry.update_api_key(provider_id, payload.api_key)
    except ValueError as exc:
        raise HTTPException(status_code=404 if str(exc) == "provider_not_found" else 400,
                            detail={"code": str(exc)}) from exc
    return {"id": provider_id, "has_api_key": True}


@router.post("/providers/{provider_id}/models", status_code=status.HTTP_201_CREATED)
def create_model(provider_id: str, payload: ModelCreate,
                 registry: ProviderRegistry = Depends(get_registry)) -> dict:
    try:
        model_id = registry.add_model(
            provider_id, payload.display_name, payload.model_name,
            {
                "tool_support": payload.tool_support,
                "structured_output": payload.structured_output,
            },
            context_window=payload.context_window,
            max_output_tokens=payload.max_output_tokens,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": str(exc)}) from exc
    model = registry.db.get_model(model_id)
    assert model is not None
    return model


@router.put("/providers/{provider_id}/models/{model_id}/capabilities")
def update_model_capabilities(
    provider_id: str,
    model_id: str,
    payload: ModelCapabilityUpdate,
    registry: ProviderRegistry = Depends(get_registry),
) -> dict:
    try:
        return registry.update_model_capabilities(
            provider_id, model_id, payload.model_dump(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": str(exc)}) from exc


@router.post("/providers/{provider_id}/models/{model_id}/probe")
async def probe_model(provider_id: str, model_id: str,
                      registry: ProviderRegistry = Depends(get_registry)) -> ProbeResult:
    try:
        resolved = registry.resolve(provider_id, model_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": str(exc)}) from exc
    result = await CapabilityProbe(resolved.adapter).run(resolved.model_name)
    if result.chat:
        probed_at = datetime.now(timezone.utc)
        registry.update_model_capabilities(provider_id, model_id, {
            "structured_output": result.structured_output_capability,
            "tool_support": "enabled" if result.tool_calling else "disabled",
            "capability_probe_status": "succeeded",
            "capability_probe_route_fingerprint": resolved.route_fingerprint,
            "capability_probe_at": probed_at.isoformat().replace("+00:00", "Z"),
            "capability_probe_expires_at": (
                probed_at + timedelta(days=7)
            ).isoformat().replace("+00:00", "Z"),
        })
    return result


class RoleBindingUpdate(BaseModel):
    primary_provider_id: str
    primary_model_id: str
    fallback_provider_id: str | None = None
    fallback_model_id: str | None = None

    @model_validator(mode="after")
    def validate_fallback_pair(self) -> "RoleBindingUpdate":
        if bool(self.fallback_provider_id) != bool(self.fallback_model_id):
            raise ValueError("fallback_provider_id and fallback_model_id must be set together")
        return self


@router.get("/role-bindings")
def list_role_bindings(registry: ProviderRegistry = Depends(get_registry)) -> list[dict]:
    return registry.db.list_role_bindings()


@router.put("/role-bindings/{role}")
def update_role_binding(role: str, payload: RoleBindingUpdate,
                        registry: ProviderRegistry = Depends(get_registry)) -> dict:
    registry.resolve(payload.primary_provider_id, payload.primary_model_id)
    if (payload.fallback_provider_id, payload.fallback_model_id) == (
        payload.primary_provider_id, payload.primary_model_id,
    ):
        raise HTTPException(status_code=400, detail={"code": "fallback_matches_primary"})
    if payload.fallback_provider_id and payload.fallback_model_id:
        registry.resolve(payload.fallback_provider_id, payload.fallback_model_id)
    registry.db.save_role_binding(role, **payload.model_dump())
    return {"role": role, **payload.model_dump()}
