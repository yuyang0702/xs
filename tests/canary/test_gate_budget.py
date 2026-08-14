import asyncio
from concurrent.futures import ThreadPoolExecutor
import hashlib

import pytest

from novel_flywheel.models import ModelResult
from tools.canary.budget import AtomicBudgetLedger, BudgetLimits, CanaryBudgetExceeded
from tools.canary.gate import (
    CanaryBoundaryAbort,
    GateState,
    PreflightGatedGateway,
    TwoPhaseGate,
)
from tools.canary.route_policy import ApprovedRoutePolicy


def h(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class FakeDelegate:
    async def complete(self, role, system, user, max_output_tokens=None, **kwargs):
        return ModelResult("{}", {"input_tokens": 3, "output_tokens": 2})


def gateway(*, verifier=lambda _request: None, timeout=2, limits=None):
    route = {
        "provider_descriptor_hash": h("provider"),
        "model_binding_hash": h("model"),
        "protocol": "fake",
    }
    policy = ApprovedRoutePolicy([{
        "role": "planning", "allowed_stages": ["planning"],
        "primary": route, "fallback": route,
    }])
    ledger = AtomicBudgetLedger(limits or BudgetLimits(10, 10, 1000, 1000, 0, 60))
    wrapped = PreflightGatedGateway(
        FakeDelegate(), gate=TwoPhaseGate(wait_timeout_seconds=timeout),
        verifier=verifier, budget_ledger=ledger, route_policy=policy,
        route_resolver=lambda _role, _kind: route,
        stage_resolver=lambda _role: ("planning", h("run")),
    )
    return wrapped, ledger


@pytest.mark.asyncio
async def test_two_phase_gate_parks_preflights_releases_and_leaves_no_task() -> None:
    wrapped, ledger = gateway()
    task = asyncio.create_task(wrapped.complete(
        "planning", "system", "user", max_output_tokens=20,
    ))
    request = await wrapped.run_initial_preflight()
    result = await asyncio.wait_for(task, timeout=2)
    assert result.text == "{}"
    assert request.role == "planning"
    assert wrapped.gate.state == GateState.RELEASED
    assert ledger.snapshot()["reservation_count"] == 1
    assert wrapped.counters() == {
        "credential_lookup_count": 0,
        "provider_client_creation_count": 0,
        "network_call_count": 0,
        "fake_model_boundary_calls": 1,
        "paid_model_call_count": 0,
    }
    assert task.done()


@pytest.mark.asyncio
async def test_every_boundary_revalidates_and_reserves_before_delegate() -> None:
    calls = []
    wrapped, ledger = gateway(verifier=lambda request: calls.append(request.ordinal))
    first = asyncio.create_task(wrapped.complete(
        "planning", "system-1", "user-1", max_output_tokens=20,
    ))
    await wrapped.run_initial_preflight()
    await first
    await wrapped.complete("planning", "system-2", "user-2", max_output_tokens=20)
    assert calls == [1, 1, 2]
    assert ledger.snapshot()["reservation_count"] == 2


@pytest.mark.asyncio
async def test_blocked_preflight_aborts_without_delegate_or_background_task() -> None:
    class Blocked(RuntimeError):
        reason_code = "build_fingerprint_unapproved"

    wrapped, ledger = gateway(verifier=lambda _request: (_ for _ in ()).throw(Blocked()))
    task = asyncio.create_task(wrapped.complete("planning", "s", "u", max_output_tokens=1))
    with pytest.raises(CanaryBoundaryAbort) as preflight:
        await wrapped.run_initial_preflight()
    assert preflight.value.reason_code == "build_fingerprint_unapproved"
    with pytest.raises(CanaryBoundaryAbort):
        await task
    assert wrapped.gate.state == GateState.ABORTED
    assert ledger.snapshot()["reservation_count"] == 0
    assert wrapped.counters()["fake_model_boundary_calls"] == 0


@pytest.mark.asyncio
async def test_unapproved_actual_route_blocks_before_delegate() -> None:
    wrapped, ledger = gateway()
    wrapped.route_resolver = lambda _role, _kind: {
        "provider_descriptor_hash": h("unapproved-provider"),
        "model_binding_hash": h("model"), "protocol": "fake",
    }
    task = asyncio.create_task(wrapped.complete("planning", "s", "u", max_output_tokens=1))
    await wrapped.run_initial_preflight()
    with pytest.raises(CanaryBoundaryAbort) as exc:
        await task
    assert exc.value.reason_code == "provider_descriptor_mismatch"
    assert ledger.snapshot()["reservation_count"] == 0
    assert wrapped.counters()["fake_model_boundary_calls"] == 0


@pytest.mark.asyncio
async def test_gate_timeout_is_distinct_and_cleans_waiter() -> None:
    wrapped, _ledger = gateway(timeout=1)
    task = asyncio.create_task(wrapped.complete("planning", "s", "u", max_output_tokens=1))
    with pytest.raises(CanaryBoundaryAbort) as exc:
        await task
    assert exc.value.reason_code == "gate_wait_timeout"
    assert wrapped.gate.state == GateState.ABORTED
    assert task.done()


def test_budget_reservation_is_atomic_under_concurrency_and_never_refunds_missing_usage() -> None:
    ledger = AtomicBudgetLedger(BudgetLimits(100, 10, 100, 100, 0, 60))

    def reserve(index):
        try:
            return ledger.reserve(
                run_id_hash=h("run"), attempt_kind="primary",
                input_tokens=1, output_tokens=1,
                estimated_cost_microunits=0,
            )
        except CanaryBudgetExceeded:
            return None

    with ThreadPoolExecutor(max_workers=20) as executor:
        results = list(executor.map(reserve, range(30)))
    accepted = [item for item in results if item is not None]
    assert len(accepted) == 10
    snapshot = ledger.snapshot()
    assert snapshot["reservation_count"] == 10
    assert snapshot["reserved_input_tokens"] == 10
    ledger.record_provider_usage(1, input_tokens=None, output_tokens=None)
    assert ledger.snapshot()["reported_usage"]["1"]["status"] == (
        "missing_reserved_value_retained"
    )


def test_all_recovery_attempt_kinds_share_one_budget() -> None:
    kinds = [
        "primary", "fallback", "protocol_retry", "scoped_repair",
        "maintenance", "review", "regeneration", "resume",
    ]
    ledger = AtomicBudgetLedger(BudgetLimits(8, 8, 80, 80, 0, 60))
    for kind in kinds:
        ledger.reserve(
            run_id_hash=h("run"), attempt_kind=kind,
            input_tokens=1, output_tokens=1, estimated_cost_microunits=0,
        )
    assert [item["attempt_kind"] for item in ledger.snapshot()["reservations"]] == kinds
