import asyncio
import hashlib

import pytest

from novel_flywheel.db import Database
from novel_flywheel.models import ModelResult
from tools.canary.artifact_binding import observe_last_legal_bindings
from tools.canary.budget import AtomicBudgetLedger, BudgetLimits
from tools.canary.gate import (
    CanaryAbortKind, CanaryBoundaryAbort, PreflightGatedGateway, TwoPhaseGate,
)
from tools.canary.monetary import CanaryMonetaryBudgetV1
from tools.canary.outcomes import CanaryOutcome, outcome_for_boundary_abort
from tools.canary.route_policy import ApprovedRoutePolicy


def h(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def make_run(db: Database) -> None:
    db.save_project("book", "Book", "short", db.path.parent / "book")
    db.create_run("run-1", "book", "short-story")


ROUTE = {
    "provider_descriptor_hash": h("provider"),
    "model_binding_hash": h("model"), "protocol": "fake",
}


class Delegate:
    def __init__(self, failure=None):
        self.calls = 0
        self.failure = failure

    async def complete(self, *args, **kwargs):
        self.calls += 1
        if self.failure:
            raise self.failure
        return ModelResult("{}", {"input_tokens": 1, "output_tokens": 1})


def make_gateway(
    *, limits: BudgetLimits, monetary=None, estimated_cost=lambda _request: 0,
    delegate=None, context=None,
):
    delegate = delegate or Delegate()
    wrapped = PreflightGatedGateway(
        delegate, gate=TwoPhaseGate(wait_timeout_seconds=2),
        verifier=lambda _request: None,
        budget_ledger=AtomicBudgetLedger(limits),
        monetary_budget=monetary,
        route_policy=ApprovedRoutePolicy([{
            "role": "planning", "allowed_stages": ["planning"],
            "primary": ROUTE, "fallback": ROUTE,
        }]),
        route_resolver=lambda _role, _kind: ROUTE,
        stage_resolver=lambda _role: ("planning", h("run")),
        estimated_cost=estimated_cost,
        workload_identifier_hash=h("workload"),
        budget_stop_context_supplier=lambda _request: context or {},
    )
    return wrapped, delegate


async def first_call(wrapped, *, output=1):
    task = asyncio.create_task(wrapped.complete(
        "planning", "system", "user", max_output_tokens=output,
    ))
    await wrapped.run_initial_preflight()
    return await task


def test_typed_outcome_mapping_keeps_budget_distinct_from_preflight() -> None:
    budget = outcome_for_boundary_abort("budget_exhausted", "cohort_call_budget_exceeded")
    mismatch = outcome_for_boundary_abort("preflight", "build_fingerprint_mismatch")
    assert budget.outcome == CanaryOutcome.CANARY_BUDGET_EXHAUSTED
    assert mismatch.outcome == CanaryOutcome.CANARY_BLOCKED_PRE_PROVIDER
    assert not budget.workflow_terminal_counted
    assert not budget.production_incident_counted


@pytest.mark.asyncio
async def test_approved_call_cap_48_blocks_49th_before_any_next_delegation() -> None:
    limits = BudgetLimits(49, 48, 1_000_000, 1_000_000, 0, 60)
    wrapped, delegate = make_gateway(limits=limits)
    await first_call(wrapped)
    for _ in range(47):
        await wrapped.complete("planning", "s", "u", max_output_tokens=1)
    before = (delegate.calls, wrapped.counters().copy())
    with pytest.raises(CanaryBoundaryAbort) as caught:
        await wrapped.complete("planning", "s", "u", max_output_tokens=1)
    assert caught.value.kind == CanaryAbortKind.BUDGET_EXHAUSTED
    assert caught.value.reason_code == "cohort_call_budget_exceeded"
    assert caught.value.budget_stop_evidence["budget_dimension_exhausted"] == "cohort_calls"
    assert caught.value.budget_stop_evidence["already_reserved_amount"] == 48
    assert (delegate.calls, wrapped.counters()) == before
    assert wrapped.budget_ledger.snapshot()["reservation_count"] == 48


@pytest.mark.asyncio
async def test_per_run_call_budget_is_an_independent_typed_dimension() -> None:
    wrapped, delegate = make_gateway(
        limits=BudgetLimits(0, 1, 100, 100, 0, 60),
    )
    task = asyncio.create_task(wrapped.complete("planning", "s", "u", max_output_tokens=1))
    with pytest.raises(CanaryBoundaryAbort) as caught:
        await wrapped.run_initial_preflight()
    with pytest.raises(CanaryBoundaryAbort):
        await task
    assert caught.value.reason_code == "single_run_call_budget_exceeded"
    assert caught.value.budget_stop_evidence["budget_dimension_exhausted"] == "per_run_calls"
    assert delegate.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(("limits", "reason", "dimension"), [
    (BudgetLimits(2, 2, 0, 100, 0, 60), "input_token_budget_exceeded", "input_tokens"),
    (BudgetLimits(2, 2, 100, 0, 0, 60), "output_token_budget_exceeded", "output_tokens"),
])
async def test_token_budget_exhaustion_is_typed(limits, reason, dimension) -> None:
    wrapped, delegate = make_gateway(limits=limits)
    task = asyncio.create_task(wrapped.complete("planning", "s", "u", max_output_tokens=1))
    with pytest.raises(CanaryBoundaryAbort) as caught:
        await wrapped.run_initial_preflight()
    with pytest.raises(CanaryBoundaryAbort):
        await task
    assert caught.value.kind == CanaryAbortKind.BUDGET_EXHAUSTED
    assert caught.value.reason_code == reason
    assert caught.value.budget_stop_evidence["budget_dimension_exhausted"] == dimension
    assert delegate.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(("currency", "reason"), [
    ("USD", "usd_cost_budget_exceeded"),
    ("CNY", "cny_cost_budget_exceeded"),
])
async def test_currency_budget_exhaustion_is_typed_and_no_partial_reservation(currency, reason) -> None:
    money = CanaryMonetaryBudgetV1(
        maximum_usd_microunits=0 if currency == "USD" else 100,
        maximum_cny_microunits=0 if currency == "CNY" else 100,
    )
    wrapped, delegate = make_gateway(
        limits=BudgetLimits(2, 2, 100, 100, 0, 60), monetary=money,
        estimated_cost=lambda _request: {currency: 1},
    )
    task = asyncio.create_task(wrapped.complete("planning", "s", "u", max_output_tokens=1))
    with pytest.raises(CanaryBoundaryAbort) as caught:
        await wrapped.run_initial_preflight()
    with pytest.raises(CanaryBoundaryAbort):
        await task
    assert caught.value.reason_code == reason
    assert caught.value.budget_stop_evidence["budget_dimension_exhausted"] == currency
    assert wrapped.budget_ledger.snapshot()["reservation_count"] == 0
    assert money.snapshot()["reservations"] == []
    assert delegate.calls == 0


@pytest.mark.asyncio
async def test_elapsed_budget_exhaustion_is_typed(monkeypatch) -> None:
    ticks = iter((0.0, 2.0, 2.0, 2.0))
    ledger = AtomicBudgetLedger(
        BudgetLimits(2, 2, 100, 100, 0, 1), monotonic=lambda: next(ticks),
    )
    wrapped, delegate = make_gateway(limits=BudgetLimits(2, 2, 100, 100, 0, 60))
    wrapped.budget_ledger = ledger
    task = asyncio.create_task(wrapped.complete("planning", "s", "u", max_output_tokens=1))
    with pytest.raises(CanaryBoundaryAbort) as caught:
        await wrapped.run_initial_preflight()
    with pytest.raises(CanaryBoundaryAbort):
        await task
    assert caught.value.reason_code == "elapsed_budget_exceeded"
    assert caught.value.budget_stop_evidence["budget_dimension_exhausted"] == "elapsed_seconds"
    assert delegate.calls == 0


def test_checkpoint_and_last_legal_artifact_exact_when_epoch_is_proven(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    make_run(db)
    db.save_workflow_node_checkpoint(
        run_id="run-1", node_key="planning", authority_sha256=h("authority"),
        input_sha256=h("input"), output_sha256=h("output"),
        status="validated", validation_stage="promoted",
        payload={"execution_epoch": "execution:1", "runtime_execution_fingerprint": h("runtime")},
    )
    observed = observe_last_legal_bindings(db, run_id="run-1", executor_binding={
        "execution_epoch": "execution:1", "runtime_execution_fingerprint": h("runtime"),
    })
    assert observed["checkpoint"]["binding_status"] == "exact"
    assert observed["last_legal_artifact"]["binding_status"] == "exact"
    assert observed["last_legal_artifact"]["identity_sha256"] == h("output")


def test_checkpoint_and_artifact_absent_are_reported_honestly(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    make_run(db)
    observed = observe_last_legal_bindings(db, run_id="run-absent", executor_binding={})
    assert observed["checkpoint"]["binding_status"] == "none_available"
    assert observed["last_legal_artifact"]["binding_status"] == "none_available"


def test_checkpoint_and_artifact_without_epoch_are_unverifiable(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    make_run(db)
    db.save_workflow_node_checkpoint(
        run_id="run-1", node_key="draft", authority_sha256=h("authority"),
        input_sha256=h("input"), output_sha256=h("output"),
        status="generated_complete", validation_stage="local_semantics", payload={},
    )
    observed = observe_last_legal_bindings(db, run_id="run-1", executor_binding={
        "execution_epoch": "execution:1", "runtime_execution_fingerprint": h("runtime"),
    })
    assert observed["checkpoint"]["binding_status"] == "unverifiable"
    assert observed["last_legal_artifact"]["binding_status"] == "unverifiable"


@pytest.mark.asyncio
async def test_previous_failure_is_preserved_when_fallback_budget_is_exhausted() -> None:
    class ProtocolInvalid(RuntimeError):
        pass

    delegate = Delegate(ProtocolInvalid("redacted"))
    wrapped, _ = make_gateway(
        limits=BudgetLimits(1, 1, 100, 100, 0, 60), delegate=delegate,
    )
    task = asyncio.create_task(wrapped.complete("planning", "s", "u", max_output_tokens=1))
    await wrapped.run_initial_preflight()
    with pytest.raises(ProtocolInvalid):
        await task
    with pytest.raises(CanaryBoundaryAbort) as caught:
        await wrapped.complete_configured_fallback(
            "planning", "s", "u", max_output_tokens=1,
        )
    evidence = caught.value.budget_stop_evidence
    assert evidence["underlying_previous_failure"] == "ProtocolInvalid"
    assert evidence["previous_route_kind"] == "primary"
    assert evidence["previous_attempt_receipt_hash"]
    assert evidence["current_requested_next_action"] == "runtime_selected_configured_fallback"
    assert delegate.calls == 1


@pytest.mark.asyncio
async def test_budget_stop_does_not_mutate_business_checkpoint_or_incident_state(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    tables = ("story_states", "story_candidates", "workflow_node_checkpoints")
    def counts():
        with db.connect() as connection:
            return {name: connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] for name in tables}
    before = counts()
    wrapped, delegate = make_gateway(limits=BudgetLimits(0, 0, 0, 0, 0, 60))
    task = asyncio.create_task(wrapped.complete("planning", "s", "u", max_output_tokens=1))
    with pytest.raises(CanaryBoundaryAbort):
        await wrapped.run_initial_preflight()
    with pytest.raises(CanaryBoundaryAbort):
        await task
    assert counts() == before
    assert delegate.calls == 0
