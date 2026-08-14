"""Deterministic fake route descriptors for C0A only."""

from __future__ import annotations

from typing import Any

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
