"""Deterministic fake route descriptors for C0A only."""

from __future__ import annotations

from typing import Any
import hashlib
import json

from novel_flywheel.runtime_fingerprint_build import domain_sha256


FAKE_PROVIDER_ID = "c0a-fake-provider-v1"
FAKE_MODEL_ID = "c0a-fake-model-v1"
SHORT_ROLES = (
    "planning", "draft", "review", "reader_review", "final_review",
    "polish", "line_edit", "maintenance",
)
SHORT_STAGES = (
    "starting", "planning", "planning_review", "causal_chain",
    "execution_manifest", "execution_manifest_review", "draft",
    "draft_validation", "draft_integrity", "review", "reader_review",
    "quality", "polish", "final_review", "maintenance",
)
C0B_MAXIMUM_OUTPUT_TOKENS_PER_DISPATCH = 32_000


def configure_fake_routes(db: Any) -> None:
    db.save_provider(
        provider_id=FAKE_PROVIDER_ID, name="C0A Fake Boundary",
        protocol="fake-boundary", base_url="https://invalid.example",
        auth_type="none", timeout_seconds=1, extra_headers={}, enabled=True,
    )
    db.save_model(
        model_id=FAKE_MODEL_ID, provider_id=FAKE_PROVIDER_ID,
        display_name="C0A Fake Model", model_name="c0a-fake-model-v1",
        context_window=128_000, max_output_tokens=32_000,
        capabilities={},
    )
    for role in SHORT_ROLES:
        db.save_role_binding(
            role, FAKE_PROVIDER_ID, FAKE_MODEL_ID,
            FAKE_PROVIDER_ID, FAKE_MODEL_ID,
        )


def fake_route_identity() -> dict[str, str]:
    provider = domain_sha256("novel-flywheel-canary-provider-descriptor-v1", {
        "provider_id": FAKE_PROVIDER_ID, "protocol": "fake-boundary",
        "auth_type": "none", "timeout_seconds": 1, "enabled": True,
        "credential_material_included": False,
    })
    model = domain_sha256("novel-flywheel-canary-model-binding-v1", {
        "model_id": FAKE_MODEL_ID, "provider_id": FAKE_PROVIDER_ID,
        "context_window": 128_000, "max_output_tokens": 32_000,
        "capabilities": {},
    })
    return {
        "provider_descriptor_hash": provider,
        "model_binding_hash": model,
        "protocol": "fake-boundary",
    }


def approved_fake_routes() -> list[dict]:
    identity = fake_route_identity()
    return [{
        "role": role, "allowed_stages": list(SHORT_STAGES),
        "primary": dict(identity), "fallback": dict(identity),
    } for role in SHORT_ROLES]


def production_route_identity(db: Any, role: str, kind: str) -> dict[str, str]:
    """Hash one current production route without exposing its endpoint."""

    binding = db.get_role_binding(role) or {}
    prefix = "fallback" if kind in {"fallback", "configured_fallback"} else "primary"
    provider = db.get_provider(binding.get(f"{prefix}_provider_id", "")) or {}
    model = db.get_model(binding.get(f"{prefix}_model_id", "")) or {}
    if not provider or not model:
        raise LookupError(f"production_{prefix}_route_missing:{role}")
    endpoint_hash = hashlib.sha256(
        str(provider.get("base_url") or "").rstrip("/").encode("utf-8")
    ).hexdigest()
    header_names = sorted((provider.get("extra_headers") or {}).keys())
    provider_hash = domain_sha256(
        "novel-flywheel-canary-provider-descriptor-v1", {
            "provider_id": provider["id"], "provider_alias": provider["name"],
            "protocol": provider["protocol"], "auth_type": provider["auth_type"],
            "timeout_seconds": provider["timeout_seconds"],
            "enabled": bool(provider["enabled"]), "endpoint_sha256": endpoint_hash,
            "extra_header_names": header_names,
            "credential_material_included": False,
        },
    )
    model_hash = domain_sha256(
        "novel-flywheel-canary-model-binding-v1", {
            "model_id": model["id"], "provider_id": provider["id"],
            "model_alias": model["model_name"],
            "context_window": model.get("context_window"),
            "max_output_tokens": model.get("max_output_tokens"),
            "capabilities_sha256": hashlib.sha256(json.dumps(
                model.get("capabilities") or {}, ensure_ascii=False,
                sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")).hexdigest(),
        },
    )
    return {
        "provider_descriptor_hash": provider_hash,
        "model_binding_hash": model_hash,
        "protocol": str(provider["protocol"]),
        "provider_alias": str(provider["name"]),
        "model_alias": str(model["model_name"]),
    }


def approved_production_routes(db: Any) -> list[dict]:
    result = []
    for role in SHORT_ROLES:
        primary = production_route_identity(db, role, "primary")
        fallback = production_route_identity(db, role, "fallback")
        result.append({
            "role": role, "allowed_stages": list(SHORT_STAGES),
            "primary": {
                key: primary[key] for key in (
                    "provider_descriptor_hash", "model_binding_hash", "protocol",
                )
            } | {
                "maximum_canary_output_tokens": (
                    C0B_MAXIMUM_OUTPUT_TOKENS_PER_DISPATCH
                ),
            },
            "fallback": {
                key: fallback[key] for key in (
                    "provider_descriptor_hash", "model_binding_hash", "protocol",
                )
            } | {
                "maximum_canary_output_tokens": (
                    C0B_MAXIMUM_OUTPUT_TOKENS_PER_DISPATCH
                ),
            },
        })
    return result


def production_route_manifest_hashes(db: Any) -> dict[str, str]:
    identities = []
    for role in SHORT_ROLES:
        for kind in ("primary", "fallback"):
            identities.append({
                "role": role, "kind": kind,
                **production_route_identity(db, role, kind),
            })
    providers = [{
        key: item[key] for key in (
            "provider_alias", "provider_descriptor_hash", "protocol",
        )
    } for item in identities]
    bindings = [{
        key: item[key] for key in (
            "role", "kind", "provider_descriptor_hash", "model_binding_hash",
            "protocol", "provider_alias", "model_alias",
        )
    } for item in identities]
    return {
        "provider_descriptor_definition_sha256": domain_sha256(
            "novel-flywheel-c0b-provider-descriptor-manifest-v1", providers,
        ),
        "role_binding_manifest_definition_sha256": domain_sha256(
            "novel-flywheel-c0b-role-binding-manifest-v1", bindings,
        ),
    }


def copy_production_execution_config(source: Any, target: Any) -> None:
    """Copy non-secret provider/model/role metadata into an isolated DB."""

    for provider in source.list_providers():
        target.save_provider(
            provider_id=provider["id"], name=provider["name"],
            protocol=provider["protocol"], base_url=provider["base_url"],
            auth_type=provider["auth_type"],
            timeout_seconds=provider["timeout_seconds"],
            extra_headers=provider["extra_headers"], enabled=provider["enabled"],
        )
        for model in source.list_models(provider["id"]):
            target.save_model(
                model_id=model["id"], provider_id=provider["id"],
                display_name=model["display_name"], model_name=model["model_name"],
                context_window=model.get("context_window"),
                max_output_tokens=model.get("max_output_tokens"),
                capabilities=model.get("capabilities") or {},
            )
    for binding in source.list_role_bindings():
        target.save_role_binding(
            binding["role"], binding["primary_provider_id"],
            binding["primary_model_id"], binding.get("fallback_provider_id"),
            binding.get("fallback_model_id"),
        )
