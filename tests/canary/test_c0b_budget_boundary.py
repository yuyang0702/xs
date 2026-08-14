import asyncio
from decimal import Decimal
import hashlib

import pytest

from novel_flywheel.models import ModelResult
from tools.canary.budget import AtomicBudgetLedger, BudgetLimits, CanaryBudgetExceeded
from tools.canary.gate import PreflightGatedGateway, TwoPhaseGate
from tools.canary.monetary import (
    CanaryMonetaryBudgetV1,
    PriceCatalogV1,
    PriceRuleV1,
)
from tools.canary.real_boundary import (
    ControlledProviderCapabilityOutcome,
    FinalAuthorizationLatch,
    GuardedCredentialStore,
    GuardedProductionGateway,
    GuardedProviderRegistry,
    RealBoundaryCounters,
    classify_provider_capability_failure,
)
from tools.canary.route_policy import ApprovedRoutePolicy


def h(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def rule(
    provider: str = "happy", model: str = "qwen-3.7-plus", *,
    currency: str = "USD", input_rate: str = "1", cached_rate: str = "0.2",
    output_rate: str = "4", group: str = "default",
    reasoning_rule: str = "included_in_completion_cap",
) -> PriceRuleV1:
    return PriceRuleV1(
        provider=provider, model=model, relay_group=group,
        currency=currency, unit_tokens=1_000_000,
        input_rate_per_unit=Decimal(input_rate),
        cached_input_rate_per_unit=Decimal(cached_rate),
        output_rate_per_unit=Decimal(output_rate),
        reasoning_token_rule=reasoning_rule,
        source_type="USER_SUPPLIED_RELAY_CONSOLE_EVIDENCE",
        evidence_sha256=h(f"{provider}/{model}/{group}"),
        effective_evidence_date="2026-08-15",
    )


def test_happy_default_and_test_prices_are_distinct() -> None:
    catalog = PriceCatalogV1([
        rule(), rule(group="test", input_rate="0.6", output_rate="2.4"),
    ])
    assert catalog.require("happy", "qwen-3.7-plus", "default").input_rate_per_unit == 1
    assert catalog.require("happy", "qwen-3.7-plus", "test").input_rate_per_unit == Decimal("0.6")
    with pytest.raises(KeyError, match="price_rule_not_found"):
        catalog.require("happy", "qwen-3.7-plus", "vip")


def test_qwen_reasoning_is_conservatively_accounted() -> None:
    price = rule(
        model="qwen-max-thinking", cached_rate="1",
        reasoning_rule="separate_if_reported",
    )
    estimate = price.cost_microunits(
        input_tokens=100, cached_input_tokens=0, output_tokens=200,
        reasoning_tokens=50,
    )
    assert estimate == 100 + (250 * 4)


def test_cny_and_usd_are_independent_hard_budgets() -> None:
    budget = CanaryMonetaryBudgetV1(maximum_usd_microunits=100, maximum_cny_microunits=200)
    budget.reserve({"USD": 100, "CNY": 150})
    with pytest.raises(CanaryBudgetExceeded, match="cny_cost_budget_exceeded"):
        budget.reserve({"CNY": 51})
    assert budget.snapshot()["reserved_cost_microunits"] == {"CNY": 150, "USD": 100}


def test_unknown_billing_failure_keeps_full_reservation() -> None:
    budget = CanaryMonetaryBudgetV1(maximum_usd_microunits=1000, maximum_cny_microunits=0)
    ordinal = budget.reserve({"USD": 400})
    budget.reconcile(ordinal, actual_costs=None, billing_receipt_reliable=False)
    snapshot = budget.snapshot()
    assert snapshot["reserved_cost_microunits"]["USD"] == 400
    assert snapshot["reconciliations"][str(ordinal)]["status"] == "unknown_billing_reservation_retained"


def test_retries_fallback_and_repair_each_reserve_a_call() -> None:
    ledger = AtomicBudgetLedger(BudgetLimits(3, 3, 100, 100, 0, 60))
    for kind in ("primary", "protocol_retry", "fallback"):
        ledger.reserve(
            run_id_hash=h("run"), attempt_kind=kind,
            input_tokens=1, output_tokens=1, estimated_cost_microunits=0,
        )
    with pytest.raises(CanaryBudgetExceeded, match="single_run_call_budget_exceeded"):
        ledger.reserve(
            run_id_hash=h("run"), attempt_kind="scoped_repair",
            input_tokens=1, output_tokens=1, estimated_cost_microunits=0,
        )


class _Secret:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def get(self, provider_id: str) -> str:
        self.events.append("credential")
        return "redacted-test-secret"

    def set(self, provider_id: str, value: str) -> None:
        raise AssertionError

    def delete(self, provider_id: str) -> None:
        raise AssertionError


class _Adapter:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def complete(self, _request):
        self.events.append("network")
        return ModelResult("{}", {"input_tokens": 1, "output_tokens": 1})


class _Registry:
    def __init__(self, events: list[str], secrets: GuardedCredentialStore) -> None:
        self.events = events
        self.secrets = secrets

    def resolve(self, _provider_id, _model_id):
        from novel_flywheel.providers.registry import ResolvedModel

        self.secrets.get("provider")
        self.events.append("provider_client")
        return ResolvedModel("provider", "model", "model", _Adapter(self.events))


class _ProductionLike:
    def __init__(self, registry: GuardedProviderRegistry) -> None:
        self.registry = registry

    async def complete_route(self, route, role, system, user, **kwargs):
        resolved = self.registry.resolve("provider", "model")
        return await resolved.adapter.complete(object())


class _SplitVerifier:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def validate_inputs(self, _request):
        self.events.append("input_validation")
        return {"validated": True}

    def run_runtime_preflight(self, _request, validated):
        assert validated == {"validated": True}
        self.events.append("runtime_preflight")


@pytest.mark.asyncio
async def test_credential_client_and_network_follow_final_authorization() -> None:
    events: list[str] = []
    latch = FinalAuthorizationLatch()
    secrets = GuardedCredentialStore(_Secret(events), latch=latch)
    counters = RealBoundaryCounters()
    registry = GuardedProviderRegistry(
        _Registry(events, secrets), latch=latch, counters=counters,
    )
    delegate = GuardedProductionGateway(
        lambda: _ProductionLike(registry), latch=latch, counters=counters,
    )
    route = {"provider_descriptor_hash": h("p"), "model_binding_hash": h("m"), "protocol": "anthropic"}
    gate = TwoPhaseGate(wait_timeout_seconds=2)
    wrapped = PreflightGatedGateway(
        delegate, gate=gate,
        verifier=_SplitVerifier(events),
        final_authorizer=lambda _request: (events.append("final_authorization"), latch.authorize("approval")),
        budget_ledger=AtomicBudgetLedger(BudgetLimits(2, 2, 100, 100, 0, 60)),
        route_policy=ApprovedRoutePolicy([{
            "role": "planning", "allowed_stages": ["planning"],
            "primary": route, "fallback": route,
        }]),
        route_resolver=lambda _role, _kind: route,
        stage_resolver=lambda _role: ("planning", h("run")),
        estimated_cost=lambda _request: (
            events.append("budget_reservation") or 0
        ),
    )
    task = asyncio.create_task(wrapped.complete_route(
        "primary", "planning", "system", "user", max_output_tokens=10,
    ))
    await wrapped.run_initial_preflight()
    await task
    assert events == [
        "input_validation", "budget_reservation", "runtime_preflight",
        "final_authorization", "credential",
        "provider_client", "network",
    ]
    assert secrets.lookup_count == 1
    assert delegate.provider_client_creation_count == 1
    assert delegate.network_call_count == 1
    assert delegate.paid_model_call_count == 1


def test_credential_lookup_is_impossible_before_authorization() -> None:
    latch = FinalAuthorizationLatch()
    secrets = GuardedCredentialStore(_Secret([]), latch=latch)
    with pytest.raises(PermissionError, match="final_authorization_required"):
        secrets.get("provider")
    assert secrets.lookup_count == 0


def test_provider_capacity_is_controlled_capability_outcome() -> None:
    outcome = classify_provider_capability_failure(
        provider="happy", model="qwen-3.7-plus", stage="draft", role="draft",
        typed_status="max_output_limit", request_budget_sha256=h("budget"),
        runtime_reaction="stopped", retry_fallback_outcome="not_started",
    )
    assert isinstance(outcome, ControlledProviderCapabilityOutcome)
    assert outcome.family == "CONTROLLED_PROVIDER_CAPABILITY_OUTCOME"
    assert not hasattr(outcome, "raw_response")
