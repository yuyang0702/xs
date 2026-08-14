"""Sanitized Production-Mirror route and capability evidence definitions."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal

from novel_flywheel.runtime_fingerprint_build import domain_sha256
from .monetary import PriceCatalogV1, PriceRuleV1


VERIFIED = "VERIFIED"
BOUNDED_UNKNOWN_ALLOWED_FOR_SMOKE = "BOUNDED_UNKNOWN_ALLOWED_FOR_SMOKE"
HARD_BLOCKER = "HARD_BLOCKER"


_ROUTES = (
    ("planning", "lingsuan_gpt", "gpt-5.6-sol", "deepseek", "deepseek-v4-pro", "anthropic"),
    ("maintenance", "lingsuan_gpt", "gpt-5.6-sol", "deepseek", "deepseek-v4-pro", "anthropic"),
    ("final_review", "lingsuan_gpt", "gpt-5.6-sol", "deepseek", "deepseek-v4-pro", "anthropic"),
    ("draft", "happy", "qwen-3.7-plus", "happy", "qwen-max-thinking", "anthropic"),
    ("review", "deepseek", "deepseek-v4-pro", "lingsuan_gpt", "gpt-5.6-sol", "anthropic"),
    ("reader_review", "doubao", "doubao-seed-character-260628", "doubao", "doubao-seed-2-0-pro-260215", "openai-responses"),
    ("polish", "lingsuan_sonnet", "claude-sonnet-5", "happy", "claude-opus-4-5", "anthropic"),
    ("line_edit", "happy", "claude-opus-4-5", "lingsuan_sonnet", "claude-sonnet-5", "anthropic"),
)


def _route_rows() -> list[dict]:
    return [{
        "role": role, "primary_provider": pp, "primary_model": pm,
        "fallback_provider": fp, "fallback_model": fm, "protocol": protocol,
        "relay_group": "default" if pp == "happy" or fp == "happy" else "not_applicable",
    } for role, pp, pm, fp, fm, protocol in _ROUTES]


def _capabilities() -> list[dict]:
    models = (
        ("lingsuan_gpt", "gpt-5.6-sol", "VERIFIED_372K", "UNKNOWN", "PARTIAL"),
        ("lingsuan_sonnet", "claude-sonnet-5", "UNKNOWN", "UNKNOWN", "PARTIAL"),
        ("happy", "qwen-3.7-plus", "UNKNOWN", "UNKNOWN", "PARTIAL"),
        ("happy", "qwen-max-thinking", "UNKNOWN", "UNKNOWN", "PARTIAL"),
        ("happy", "claude-opus-4-5", "UNKNOWN", "UNKNOWN", "PARTIAL"),
        ("deepseek", "deepseek-v4-pro", "VERIFIED_1M", "VERIFIED_384K", "VERIFIED"),
        ("doubao", "doubao-seed-character-260628", "UNKNOWN", "UNKNOWN", "VERIFIED_DISPATCH"),
        ("doubao", "doubao-seed-2-0-pro-260215", "BOUNDED_256K_PRICE_TIERS", "UNKNOWN", "VERIFIED_DISPATCH"),
    )
    return [{
        "provider": provider, "model": model, "context": context,
        "max_output": maximum, "protocol_capability": protocol,
        "identity": VERIFIED, "pricing": VERIFIED,
        "readiness": (
            VERIFIED if context.startswith("VERIFIED") and maximum.startswith("VERIFIED")
            else BOUNDED_UNKNOWN_ALLOWED_FOR_SMOKE
        ),
    } for provider, model, context, maximum, protocol in models]


def production_mirror_manifest() -> dict:
    body = {
        "schema": "ProductionMirrorRouteManifestV1", "version": 1,
        "routes": _route_rows(), "capability_evidence": _capabilities(),
        "route_mutation_allowed": False,
    }
    return {
        **deepcopy(body),
        "definition_sha256": domain_sha256(
            "novel-flywheel-c0b-production-mirror-route-v1", body,
        ),
    }


def validate_production_mirror(routes: list[dict]) -> dict:
    expected = _route_rows()
    return {
        "schema": "ProductionMirrorRouteValidationV1",
        "status": "EXACT_MATCH" if routes == expected else "ROUTE_DRIFT",
        "expected_definition_sha256": production_mirror_manifest()["definition_sha256"],
    }


def protocol_evidence_matrix(routes: list[dict]) -> dict:
    entries: list[dict] = []
    for route in routes:
        providers = {route["primary_provider"], route["fallback_provider"]}
        for provider in sorted(providers):
            if any(item["provider"] == provider for item in entries):
                continue
            configured = next(
                item["protocol"] for item in routes
                if provider in {item["primary_provider"], item["fallback_provider"]}
            )
            if provider == "happy" and configured == "anthropic":
                status = "PARTIAL_EVIDENCE"
                evidence = "OpenAI Chat verified; Anthropic relay endpoint is only partially evidenced"
            elif provider == "lingsuan_gpt" or provider == "lingsuan_sonnet":
                status = "PARTIAL_EVIDENCE"
                evidence = "current production Anthropic dispatch path; public capability detail unavailable"
            else:
                status = "EXACT_MATCH"
                evidence = "official/direct protocol and current configured dispatch agree"
            entries.append({
                "provider": provider, "configured_protocol": configured,
                "status": status, "evidence_summary": evidence,
            })
    return {"schema": "RouteProtocolEvidenceMatrixV1", "entries": entries}


def production_price_catalog() -> PriceCatalogV1:
    """Current approved evidence rates; no currency normalization."""

    def price(
        provider: str, model: str, currency: str, input_rate: str,
        cached_rate: str, output_rate: str, source_type: str,
        *, group: str = "default", reasoning: str = "included_in_completion_cap",
    ) -> PriceRuleV1:
        evidence = {
            "provider": provider, "model": model, "group": group,
            "currency": currency, "input": input_rate, "cached": cached_rate,
            "output": output_rate, "source_type": source_type,
            "effective_date": "2026-08-15",
        }
        return PriceRuleV1(
            provider=provider, model=model, relay_group=group,
            currency=currency, unit_tokens=1_000_000,
            input_rate_per_unit=Decimal(input_rate),
            cached_input_rate_per_unit=Decimal(cached_rate),
            output_rate_per_unit=Decimal(output_rate),
            reasoning_token_rule=reasoning, source_type=source_type,
            evidence_sha256=domain_sha256(
                "novel-flywheel-c0b-price-evidence-v1", evidence,
            ),
            effective_evidence_date="2026-08-15",
        )

    relay = "USER_SUPPLIED_RELAY_CONSOLE_EVIDENCE"
    official = "OFFICIAL_PROVIDER_PUBLIC_EVIDENCE"
    return PriceCatalogV1([
        price("happy", "qwen-3.7-plus", "USD", "1", ".2", "4", relay),
        price(
            "happy", "qwen-max-thinking", "USD", "1", "1", "4", relay,
            reasoning="separate_if_reported",
        ),
        price("happy", "claude-opus-4-5", "USD", "5", "5", "25", relay),
        price("lingsuan_gpt", "gpt-5.6-sol", "CNY", "1.14", ".114", "6.84", relay),
        price("lingsuan_sonnet", "claude-sonnet-5", "CNY", "1", ".1", "5", relay),
        price("deepseek", "deepseek-v4-pro", "USD", "1.32", ".044", "3.96", official),
        price("doubao", "doubao-seed-character-260628", "CNY", ".8", ".16", "2", official),
        # Smoke input is <32K. Larger tier transitions are separately retained
        # in the evidence report and are blocked by the per-request input cap.
        price("doubao", "doubao-seed-2-0-pro-260215", "CNY", "3.2", "3.2", "16", official),
    ])
