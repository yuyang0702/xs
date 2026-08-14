"""Bounded two-phase model-boundary gate and conservative wrapper."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import inspect
from typing import Any, Awaitable, Callable
from collections.abc import Mapping

from novel_flywheel.context_policy import estimate_input_tokens

from .budget import AtomicBudgetLedger, CanaryBudgetExceeded
from .monetary import CanaryMonetaryBudgetV1
from .route_policy import ApprovedRoutePolicy, CanaryRouteBlocked, RouteObservation


class GateState(str, Enum):
    PARKED = "PARKED"
    PREFLIGHT_RUNNING = "PREFLIGHT_RUNNING"
    APPROVED = "APPROVED"
    RELEASED = "RELEASED"
    BLOCKED = "BLOCKED"
    ABORTED = "ABORTED"


class CanaryBoundaryAbort(asyncio.CancelledError):
    """Cancellation-shaped abort so workflow failure/incident handlers do not own it."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True)
class BoundaryRequest:
    stage: str
    role: str
    ordinal: int
    route_kind: str
    provider_descriptor_hash: str
    model_binding_hash: str
    protocol: str
    contract_sha256: str | None
    system_sha256: str
    user_sha256: str
    input_tokens: int
    output_tokens: int
    retry_fallback_reason: str | None
    run_id_hash: str


class TwoPhaseGate:
    def __init__(self, *, wait_timeout_seconds: int) -> None:
        if wait_timeout_seconds <= 0:
            raise ValueError("gate_wait_timeout_invalid")
        self.wait_timeout_seconds = wait_timeout_seconds
        self.state = GateState.PARKED
        self.reason_code: str | None = None
        self._arrived = asyncio.Event()
        self._released = asyncio.Event()
        self._lock = asyncio.Lock()
        self.boundary: BoundaryRequest | None = None

    async def park(self, boundary: BoundaryRequest) -> None:
        async with self._lock:
            if self.boundary is not None:
                raise CanaryBoundaryAbort("gate_boundary_already_parked")
            self.boundary = boundary
            self._arrived.set()
        try:
            await asyncio.wait_for(
                self._released.wait(), timeout=self.wait_timeout_seconds,
            )
        except TimeoutError as exc:
            async with self._lock:
                self.state = GateState.ABORTED
                self.reason_code = "gate_wait_timeout"
            raise CanaryBoundaryAbort("gate_wait_timeout") from exc
        except asyncio.CancelledError:
            async with self._lock:
                self.state = GateState.ABORTED
                self.reason_code = self.reason_code or "worker_cancelled_while_parked"
            raise
        if self.state != GateState.RELEASED:
            raise CanaryBoundaryAbort(self.reason_code or "canary_preflight_blocked")

    async def wait_until_parked(self) -> BoundaryRequest:
        try:
            await asyncio.wait_for(
                self._arrived.wait(), timeout=self.wait_timeout_seconds,
            )
        except TimeoutError as exc:
            async with self._lock:
                self.state = GateState.ABORTED
                self.reason_code = "model_boundary_not_reached"
            raise CanaryBoundaryAbort("model_boundary_not_reached") from exc
        assert self.boundary is not None
        return self.boundary

    async def begin_preflight(self) -> None:
        async with self._lock:
            if self.state != GateState.PARKED or self.boundary is None:
                raise CanaryBoundaryAbort("gate_preflight_transition_invalid")
            self.state = GateState.PREFLIGHT_RUNNING

    async def approve_and_release(self) -> None:
        async with self._lock:
            if self.state != GateState.PREFLIGHT_RUNNING:
                raise CanaryBoundaryAbort("gate_approval_transition_invalid")
            self.state = GateState.APPROVED
            self.state = GateState.RELEASED
            self._released.set()

    async def block_and_abort(self, reason_code: str) -> None:
        async with self._lock:
            if self.state not in {GateState.PARKED, GateState.PREFLIGHT_RUNNING}:
                return
            self.state = GateState.BLOCKED
            self.reason_code = reason_code
            self.state = GateState.ABORTED
            self._released.set()

    def snapshot(self) -> dict:
        return {
            "state": self.state.value,
            "reason_code": self.reason_code,
            "boundary": asdict(self.boundary) if self.boundary else None,
        }


class PreflightGatedGateway:
    """Wraps a fake or future delegate without changing Runtime behavior."""

    def __init__(
        self, delegate: Any, *, gate: TwoPhaseGate,
        verifier: Callable[[BoundaryRequest], Any],
        final_authorizer: Callable[[BoundaryRequest], Any] | None = None,
        budget_ledger: AtomicBudgetLedger,
        route_policy: ApprovedRoutePolicy,
        route_resolver: Callable[[str, str], dict[str, str]],
        stage_resolver: Callable[[str], tuple[str, str]],
        estimated_cost: Callable[[BoundaryRequest], int | Mapping[str, int]] = lambda _request: 0,
        monetary_budget: CanaryMonetaryBudgetV1 | None = None,
        actual_cost: Callable[[BoundaryRequest, Mapping[str, Any]], tuple[Mapping[str, int] | None, bool]] | None = None,
    ) -> None:
        self.delegate = delegate
        self.gate = gate
        self.verifier = verifier
        self.final_authorizer = final_authorizer
        self.budget_ledger = budget_ledger
        self.route_policy = route_policy
        self.route_resolver = route_resolver
        self.stage_resolver = stage_resolver
        self.estimated_cost = estimated_cost
        self.monetary_budget = monetary_budget
        self.actual_cost = actual_cost
        self._ordinal = 0
        self._first_boundary = True
        self._authorized_ordinals: set[int] = set()
        self.boundary_ledger: list[dict] = []
        self.fake_model_boundary_calls = 0
        self.credential_lookup_count = 0
        self.provider_client_creation_count = 0
        self.network_call_count = 0
        self.paid_model_call_count = 0

    @staticmethod
    def _hash(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _request(
        self, role: str, system: str, user: str, max_output_tokens: int | None,
        *, contract_sha256: str | None, route_kind: str = "primary",
        retry_fallback_reason: str | None = None,
    ) -> BoundaryRequest:
        self._ordinal += 1
        stage, run_id_hash = self.stage_resolver(role)
        route = self.route_resolver(role, route_kind)
        return BoundaryRequest(
            stage=stage, role=role, ordinal=self._ordinal,
            route_kind=route_kind,
            provider_descriptor_hash=route["provider_descriptor_hash"],
            model_binding_hash=route["model_binding_hash"],
            protocol=route["protocol"], contract_sha256=contract_sha256,
            system_sha256=self._hash(system), user_sha256=self._hash(user),
            input_tokens=estimate_input_tokens(system + "\n" + user),
            output_tokens=max_output_tokens or 0,
            retry_fallback_reason=retry_fallback_reason,
            run_id_hash=run_id_hash,
        )

    async def _authorize(self, request: BoundaryRequest) -> None:
        observation = RouteObservation(
            stage=request.stage, role=request.role, ordinal=request.ordinal,
            route_kind=request.route_kind,
            provider_descriptor_hash=request.provider_descriptor_hash,
            model_binding_hash=request.model_binding_hash,
            protocol=request.protocol, contract_sha256=request.contract_sha256,
            output_budget=request.output_tokens,
            retry_fallback_reason=request.retry_fallback_reason,
        )
        try:
            self.route_policy.verify(observation)
            validate_inputs = getattr(self.verifier, "validate_inputs", None)
            validated_inputs = (
                validate_inputs(request) if callable(validate_inputs) else None
            )
            # C0B ordering is deliberate: reserve the complete worst-case
            # call after immutable input checks and before Runtime preflight
            # and final authorization.
            cost = self.estimated_cost(request)
            monetary_ordinal = None
            if isinstance(cost, Mapping):
                if self.monetary_budget is None:
                    raise CanaryBudgetExceeded("monetary_budget_missing")
                monetary_ordinal = self.monetary_budget.reserve(cost)
                legacy_cost = 0
            else:
                legacy_cost = cost
            reservation = self.budget_ledger.reserve(
                run_id_hash=request.run_id_hash,
                attempt_kind=request.route_kind,
                input_tokens=request.input_tokens,
                output_tokens=request.output_tokens,
                estimated_cost_microunits=legacy_cost,
            )
            runtime_preflight = getattr(
                self.verifier, "run_runtime_preflight", None,
            )
            result = (
                runtime_preflight(request, validated_inputs)
                if validated_inputs is not None and callable(runtime_preflight)
                else self.verifier(request)
            )
            if inspect.isawaitable(result):
                await result
            if self.final_authorizer is not None:
                authorization = self.final_authorizer(request)
                if inspect.isawaitable(authorization):
                    await authorization
        except (CanaryRouteBlocked, CanaryBudgetExceeded) as exc:
            raise CanaryBoundaryAbort(exc.reason_code) from exc
        self.boundary_ledger.append({
            **asdict(request), "reservation_ordinal": reservation.ordinal,
            "monetary_reservation_ordinal": monetary_ordinal,
            "authorization_status": "approved",
        })
        self._authorized_ordinals.add(request.ordinal)

    async def run_initial_preflight(self) -> BoundaryRequest:
        request = await self.gate.wait_until_parked()
        await self.gate.begin_preflight()
        try:
            await self._authorize(request)
        except Exception as exc:
            reason = getattr(exc, "reason_code", "canary_preflight_failed")
            await self.gate.block_and_abort(reason)
            raise CanaryBoundaryAbort(reason) from exc
        await self.gate.approve_and_release()
        return request

    async def _dispatch(self, request: BoundaryRequest, method: str, *args, **kwargs):
        if self._first_boundary:
            self._first_boundary = False
            await self.gate.park(request)
        if request.ordinal not in self._authorized_ordinals:
            try:
                await self._authorize(request)
            except Exception as exc:
                reason = getattr(exc, "reason_code", "canary_preflight_failed")
                raise CanaryBoundaryAbort(reason) from exc
        self.fake_model_boundary_calls += 1
        ledger_entry = self.boundary_ledger[-1]

        def retain_failed_reservations() -> None:
            self.budget_ledger.record_provider_usage(
                ledger_entry["reservation_ordinal"],
                input_tokens=None, output_tokens=None,
            )
            monetary_ordinal = ledger_entry.get("monetary_reservation_ordinal")
            if monetary_ordinal is not None and self.monetary_budget is not None:
                self.monetary_budget.reconcile(
                    int(monetary_ordinal), actual_costs=None,
                    billing_receipt_reliable=False,
                )

        try:
            result = await getattr(self.delegate, method)(*args, **kwargs)
        except asyncio.CancelledError:
            retain_failed_reservations()
            ledger_entry["provider_observation"] = {
                "status": "cancelled", "typed_failure": "CancelledError",
                "raw_content_included": False,
            }
            raise
        except Exception as exc:
            retain_failed_reservations()
            ledger_entry["provider_observation"] = {
                "status": "failed", "typed_failure": type(exc).__name__,
                "raw_content_included": False,
            }
            raise
        receipt = getattr(result, "receipt", {}) or {}
        def hashed(field: str) -> str | None:
            value = receipt.get(field)
            return self._hash(str(value)) if value not in {None, ""} else None

        ledger_entry["provider_observation"] = {
            "status": "completed",
            "http_status_class": receipt.get("http_status_class"),
            "provider_request_id_hash": hashed("provider_request_id"),
            "observed_provider_model_identity_hash": hashed("model"),
            "input_tokens": receipt.get("input_tokens"),
            "cached_input_tokens": receipt.get("cached_input_tokens"),
            "output_tokens": receipt.get("output_tokens"),
            "reasoning_tokens": receipt.get("reasoning_tokens"),
            "finish_reason": receipt.get("finish_reason"),
            "response_sha256": self._hash(str(getattr(result, "text", ""))),
            "raw_content_included": False,
        }
        self.budget_ledger.record_provider_usage(
            self.boundary_ledger[-1]["reservation_ordinal"],
            input_tokens=receipt.get("input_tokens"),
            output_tokens=receipt.get("output_tokens"),
        )
        monetary_ordinal = self.boundary_ledger[-1].get(
            "monetary_reservation_ordinal"
        )
        if monetary_ordinal is not None and self.monetary_budget is not None:
            if self.actual_cost is None:
                actual_costs, reliable = None, False
            else:
                actual_costs, reliable = self.actual_cost(request, receipt)
            self.monetary_budget.reconcile(
                int(monetary_ordinal), actual_costs=actual_costs,
                billing_receipt_reliable=reliable,
            )
        return result

    async def complete(
        self, role: str, system: str, user: str,
        max_output_tokens: int | None = None, **kwargs,
    ):
        request = self._request(role, system, user, max_output_tokens,
                                contract_sha256=None)
        return await self._dispatch(
            request, "complete", role, system, user,
            max_output_tokens=max_output_tokens, **kwargs,
        )

    async def complete_primary(
        self, role: str, system: str, user: str,
        max_output_tokens: int | None = None, **kwargs,
    ):
        request = self._request(role, system, user, max_output_tokens,
                                contract_sha256=None)
        method = "complete_primary" if hasattr(self.delegate, "complete_primary") else "complete"
        return await self._dispatch(
            request, method, role, system, user,
            max_output_tokens=max_output_tokens, **kwargs,
        )

    async def complete_configured_fallback(
        self, role: str, system: str, user: str,
        max_output_tokens: int | None = None, **kwargs,
    ):
        request = self._request(
            role, system, user, max_output_tokens, contract_sha256=None,
            route_kind="configured_fallback",
            retry_fallback_reason="runtime_selected_configured_fallback",
        )
        method = (
            "complete_configured_fallback"
            if hasattr(self.delegate, "complete_configured_fallback") else "complete"
        )
        return await self._dispatch(
            request, method, role, system, user,
            max_output_tokens=max_output_tokens, **kwargs,
        )

    async def complete_route(
        self, route: str, role: str, system: str, user: str, *,
        max_output_tokens: int | None = None, contract: Any | None = None,
        **kwargs,
    ):
        route_kind = "configured_fallback" if route == "configured_fallback" else "primary"
        request = self._request(
            role, system, user, max_output_tokens,
            contract_sha256=(contract.schema_sha256() if contract is not None else None),
            route_kind=route_kind,
            retry_fallback_reason=(
                "runtime_selected_configured_fallback"
                if route_kind == "configured_fallback" else None
            ),
        )
        if hasattr(self.delegate, "complete_route"):
            return await self._dispatch(
                request, "complete_route", route, role, system, user,
                max_output_tokens=max_output_tokens, contract=contract, **kwargs,
            )
        method = (
            "complete_configured_fallback"
            if route_kind == "configured_fallback" else "complete_primary"
        )
        return await self._dispatch(
            request, method, role, system, user,
            max_output_tokens=max_output_tokens, **kwargs,
        )

    async def complete_structured(
        self, role: str, system: str, user: str, contract: Any, *,
        max_output_tokens: int | None = None, **kwargs,
    ):
        contract_sha256 = contract.schema_sha256()
        request = self._request(
            role, system, user, max_output_tokens,
            contract_sha256=contract_sha256,
        )
        return await self._dispatch(
            request, "complete_structured", role, system, user, contract,
            max_output_tokens=max_output_tokens, **kwargs,
        )

    def has_configured_fallback(self, role: str) -> bool:
        return bool(self.route_resolver(role, "fallback"))

    def counters(self) -> dict[str, int]:
        return {
            "credential_lookup_count": self.credential_lookup_count,
            "provider_client_creation_count": self.provider_client_creation_count,
            "network_call_count": self.network_call_count,
            "fake_model_boundary_calls": self.fake_model_boundary_calls,
            "paid_model_call_count": self.paid_model_call_count,
        }
