"""Authorization latch and production-gateway delegation for C0B.

No provider protocol is implemented here.  The guarded delegate calls the
existing production ModelGateway only after final approval authorization.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable


class FinalAuthorizationLatch:
    def __init__(self) -> None:
        self._authorized = False
        self.authorization_id: str | None = None

    def authorize(self, authorization_id: str) -> None:
        if not authorization_id:
            raise PermissionError("final_authorization_id_required")
        self._authorized = True
        self.authorization_id = authorization_id

    def require(self) -> None:
        if not self._authorized:
            raise PermissionError("final_authorization_required")

    @property
    def authorized(self) -> bool:
        return self._authorized


class GuardedCredentialStore:
    def __init__(self, delegate: Any, *, latch: FinalAuthorizationLatch) -> None:
        self.delegate = delegate
        self.latch = latch
        self.lookup_count = 0
        self.mutation_count = 0

    def get(self, provider_id: str) -> str | None:
        self.latch.require()
        self.lookup_count += 1
        return self.delegate.get(provider_id)

    def set(self, provider_id: str, value: str) -> None:
        self.mutation_count += 1
        raise PermissionError("credential_mutation_forbidden_in_canary")

    def delete(self, provider_id: str) -> None:
        self.mutation_count += 1
        raise PermissionError("credential_mutation_forbidden_in_canary")


@dataclass
class RealBoundaryCounters:
    provider_client_creation_count: int = 0
    network_call_count: int = 0
    paid_model_call_count: int = 0


class GuardedProviderAdapter:
    """Count the exact production adapter boundary, never raw provider data."""

    def __init__(
        self, delegate: Any, *, latch: FinalAuthorizationLatch,
        counters: RealBoundaryCounters,
    ) -> None:
        self.delegate = delegate
        self.latch = latch
        self.counters = counters

    async def complete(self, request: Any) -> Any:
        self.latch.require()
        # This is the existing production adapter's network-dispatch boundary.
        # Billing is conservatively counted as attempted once this boundary is
        # entered; reconciliation decides whether a reliable receipt exists.
        self.counters.network_call_count += 1
        self.counters.paid_model_call_count += 1
        return await self.delegate.complete(request)


class GuardedProviderRegistry:
    """Wrap successful production registry resolution with an adapter guard."""

    def __init__(
        self, delegate: Any, *, latch: FinalAuthorizationLatch,
        counters: RealBoundaryCounters,
    ) -> None:
        self.delegate = delegate
        self.latch = latch
        self.counters = counters

    def resolve(self, provider_id: str, model_id: str) -> Any:
        self.latch.require()
        resolved = self.delegate.resolve(provider_id, model_id)
        # ProviderRegistry.resolve constructs the concrete production adapter.
        # Count only successful construction, not an attempted lookup.
        self.counters.provider_client_creation_count += 1
        return replace(
            resolved,
            adapter=GuardedProviderAdapter(
                resolved.adapter, latch=self.latch, counters=self.counters,
            ),
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self.delegate, name)


class GuardedProductionGateway:
    """Lazily obtain and call the production gateway after authorization."""

    def __init__(
        self, gateway_supplier: Callable[[], Any], *,
        latch: FinalAuthorizationLatch,
        counters: RealBoundaryCounters | None = None,
    ) -> None:
        self.gateway_supplier = gateway_supplier
        self.latch = latch
        self.counters = counters or RealBoundaryCounters()
        self._gateway: Any | None = None

    def _delegate(self) -> Any:
        self.latch.require()
        if self._gateway is None:
            self._gateway = self.gateway_supplier()
        return self._gateway

    async def complete_route(self, route: str, role: str, system: str, user: str, **kwargs):
        gateway = self._delegate()
        return await gateway.complete_route(route, role, system, user, **kwargs)

    async def complete_primary(self, role: str, system: str, user: str, **kwargs):
        return await self.complete_route("primary", role, system, user, **kwargs)

    async def complete_configured_fallback(self, role: str, system: str, user: str, **kwargs):
        return await self.complete_route(
            "configured_fallback", role, system, user, **kwargs,
        )

    def has_configured_fallback(self, role: str) -> bool:
        return bool(self._delegate().has_configured_fallback(role))

    @property
    def provider_client_creation_count(self) -> int:
        return self.counters.provider_client_creation_count

    @property
    def network_call_count(self) -> int:
        return self.counters.network_call_count

    @property
    def paid_model_call_count(self) -> int:
        return self.counters.paid_model_call_count


@dataclass(frozen=True)
class ControlledProviderCapabilityOutcome:
    family: str
    provider: str
    model: str
    stage: str
    role: str
    typed_status: str
    request_budget_sha256: str
    runtime_reaction: str
    retry_fallback_outcome: str
    first_divergent_boundary_ordinal: int | None = None


def classify_provider_capability_failure(**payload: str) -> ControlledProviderCapabilityOutcome:
    return ControlledProviderCapabilityOutcome(
        family="CONTROLLED_PROVIDER_CAPABILITY_OUTCOME", **payload,
    )
