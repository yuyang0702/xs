import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from novel_flywheel.models import ModelResult
from novel_flywheel.reliability_trace import BestEffortTraceSink
from tools.canary.approval_profiles import approval_profile
from tools.canary.artifact_hash import tree_manifest
from tools.canary.budget import AtomicBudgetLedger, BudgetLimits
from tools.canary.gate import PreflightGatedGateway, TwoPhaseGate
from tools.canary.goal_stop import (
    CanaryObservationGoalReachedStop,
    ObservationGoalLatch,
    STOP_OUTCOME,
    STOP_REASON,
    capture_reliability_trace_goal,
)
from tools.canary.outcomes import observation_goal_stopped_outcome
from tools.canary.route_policy import ApprovedRoutePolicy


def h(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def exact_target() -> dict:
    return {
        "event_type": "diagnostic_strict_tool_shape",
        "stage_id": "planning_adaptation_whole_receipt",
        "observation_status": "confirmed",
        "payload": {
            "target_status": "target",
            "observation_status": "exact",
            "observation_sha256": h("observation"),
            "shape_correlation_sha256": h("correlation"),
            "strict_tool_decision": "accept_unique_expected",
            "strict_tool_failure_code": None,
        },
    }


class CountingBoundary:
    def __init__(
        self, latch: ObservationGoalLatch, *, target_call: int = 10,
        fail_after_target: bool = False,
    ) -> None:
        self.latch = latch
        self.target_call = target_call
        self.fail_after_target = fail_after_target
        self.credential = 0
        self.client = 0
        self.network = 0
        self.paid = 0
        self.completed = 0

    async def complete(self, role, system, user, max_output_tokens=None, **kwargs):
        self.credential += 1
        self.client += 1
        self.network += 1
        self.paid += 1
        ordinal = self.network
        if ordinal == self.target_call:
            self.latch.observe(exact_target())
            if self.fail_after_target:
                raise RuntimeError("current_boundary_business_failure")
        self.completed += 1
        return ModelResult(
            "{}", {
                "input_tokens": 3, "output_tokens": 2,
                "finish_reason": "tool_use" if ordinal == self.target_call else "end_turn",
            },
        )


def gateway(
    tmp_path: Path, *, target_call: int = 10, fail_after_target: bool = False,
) -> tuple[PreflightGatedGateway, AtomicBudgetLedger, CountingBoundary, ObservationGoalLatch]:
    latch = ObservationGoalLatch(receipt_path=tmp_path / "goal-receipt.json")
    delegate = CountingBoundary(
        latch, target_call=target_call, fail_after_target=fail_after_target,
    )
    route = {
        "provider_descriptor_hash": h("provider"),
        "model_binding_hash": h("model"),
        "protocol": "fake",
    }
    ledger = AtomicBudgetLedger(BudgetLimits(30, 30, 10000, 10000, 0, 60))
    wrapped = PreflightGatedGateway(
        delegate,
        gate=TwoPhaseGate(wait_timeout_seconds=2),
        verifier=lambda _request: None,
        budget_ledger=ledger,
        route_policy=ApprovedRoutePolicy([{
            "role": "planning", "allowed_stages": ["planning"],
            "primary": route, "fallback": route,
        }]),
        route_resolver=lambda _role, _kind: route,
        stage_resolver=lambda _role: ("planning", h("run")),
        observation_goal_latch=latch,
    )
    return wrapped, ledger, delegate, latch


async def run_boundaries(wrapped: PreflightGatedGateway, count: int) -> None:
    first = asyncio.create_task(wrapped.complete(
        "planning", "system-1", "user-1", max_output_tokens=20,
    ))
    await wrapped.run_initial_preflight()
    await first
    for ordinal in range(2, count + 1):
        await wrapped.complete(
            "planning", f"system-{ordinal}", f"user-{ordinal}",
            max_output_tokens=20,
        )


@pytest.mark.asyncio
async def test_call_10_goal_blocks_call_11_dispatch(tmp_path: Path) -> None:
    wrapped, _ledger, delegate, latch = gateway(tmp_path)
    await run_boundaries(wrapped, 10)
    with pytest.raises(CanaryObservationGoalReachedStop):
        await wrapped.complete("planning", "system-11", "user-11", max_output_tokens=20)
    assert delegate.network == 10
    assert latch.snapshot()["first_blocked_boundary_ordinal"] == 11


@pytest.mark.asyncio
async def test_calls_before_target_are_unchanged(tmp_path: Path) -> None:
    wrapped, ledger, delegate, latch = gateway(tmp_path)
    await run_boundaries(wrapped, 9)
    assert delegate.completed == 9
    assert ledger.snapshot()["reservation_count"] == 9
    assert latch.reached is False


@pytest.mark.asyncio
async def test_target_boundary_completes_and_persists_provider_receipt(tmp_path: Path) -> None:
    wrapped, _ledger, delegate, latch = gateway(tmp_path)
    await run_boundaries(wrapped, 10)
    assert delegate.completed == 10
    assert wrapped.boundary_ledger[-1]["provider_observation"]["status"] == "completed"
    assert latch.snapshot()["observation_goal_reached"] is True


@pytest.mark.asyncio
async def test_post_goal_credential_lookup_is_zero(tmp_path: Path) -> None:
    wrapped, _ledger, delegate, _latch = gateway(tmp_path)
    await run_boundaries(wrapped, 10)
    before = delegate.credential
    with pytest.raises(CanaryObservationGoalReachedStop):
        await wrapped.complete("planning", "s", "u", max_output_tokens=20)
    assert delegate.credential == before


@pytest.mark.asyncio
async def test_post_goal_provider_client_creation_is_zero(tmp_path: Path) -> None:
    wrapped, _ledger, delegate, _latch = gateway(tmp_path)
    await run_boundaries(wrapped, 10)
    before = delegate.client
    with pytest.raises(CanaryObservationGoalReachedStop):
        await wrapped.complete("planning", "s", "u", max_output_tokens=20)
    assert delegate.client == before


@pytest.mark.asyncio
async def test_post_goal_network_dispatch_is_zero(tmp_path: Path) -> None:
    wrapped, _ledger, delegate, _latch = gateway(tmp_path)
    await run_boundaries(wrapped, 10)
    before = delegate.network
    with pytest.raises(CanaryObservationGoalReachedStop):
        await wrapped.complete("planning", "s", "u", max_output_tokens=20)
    assert delegate.network == before


@pytest.mark.asyncio
async def test_post_goal_paid_call_is_zero(tmp_path: Path) -> None:
    wrapped, _ledger, delegate, _latch = gateway(tmp_path)
    await run_boundaries(wrapped, 10)
    before = delegate.paid
    with pytest.raises(CanaryObservationGoalReachedStop):
        await wrapped.complete("planning", "s", "u", max_output_tokens=20)
    assert delegate.paid == before


@pytest.mark.asyncio
async def test_blocked_call_reserves_no_budget(tmp_path: Path) -> None:
    wrapped, ledger, _delegate, _latch = gateway(tmp_path)
    await run_boundaries(wrapped, 10)
    before = ledger.snapshot()
    with pytest.raises(CanaryObservationGoalReachedStop):
        await wrapped.complete("planning", "s", "u", max_output_tokens=20)
    after = ledger.snapshot()
    assert after["reservation_count"] == before["reservation_count"] == 10
    assert after["reserved_output_tokens"] == before["reserved_output_tokens"]


def test_repeated_observation_is_idempotent_and_first_exact_target_wins(tmp_path: Path) -> None:
    latch = ObservationGoalLatch(receipt_path=tmp_path / "goal.json")
    first = exact_target()
    second = exact_target()
    second["payload"]["observation_sha256"] = h("second")
    assert latch.observe(first) is True
    assert latch.observe(second) is False
    snapshot = latch.snapshot()
    assert snapshot["first_exact_target"]["observation_sha256"] == h("observation")
    assert snapshot["duplicate_observation_count"] == 1


@pytest.mark.asyncio
async def test_concurrent_next_dispatch_race_is_serialized_and_blocked(tmp_path: Path) -> None:
    wrapped, ledger, delegate, _latch = gateway(tmp_path, target_call=2)
    await run_boundaries(wrapped, 1)
    target = asyncio.create_task(wrapped.complete(
        "planning", "target", "target", max_output_tokens=20,
    ))
    await asyncio.sleep(0)
    following = asyncio.create_task(wrapped.complete(
        "planning", "following", "following", max_output_tokens=20,
    ))
    await target
    with pytest.raises(CanaryObservationGoalReachedStop):
        await following
    assert delegate.network == 2
    assert ledger.snapshot()["reservation_count"] == 2


def test_trace_sink_failure_is_fail_closed_after_exact_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    latch = ObservationGoalLatch(receipt_path=tmp_path / "goal.json")
    monkeypatch.setattr(
        BestEffortTraceSink, "emit",
        lambda _sink, _event: (_ for _ in ()).throw(OSError("sink failed")),
    )
    with capture_reliability_trace_goal(latch):
        sink = BestEffortTraceSink(tmp_path / "trace.jsonl", enabled=True)
        assert sink.emit(exact_target()) is False
    snapshot = latch.snapshot()
    assert snapshot["observation_goal_reached"] is True
    assert snapshot["sink_failure_count"] == 1
    with pytest.raises(CanaryObservationGoalReachedStop):
        latch.raise_if_reached(boundary_ordinal=11)


def test_goal_stop_is_not_workflow_terminal_or_production_incident() -> None:
    record = observation_goal_stopped_outcome(STOP_REASON)
    assert record.outcome.value == STOP_OUTCOME
    assert record.workflow_terminal_counted is False
    assert record.production_incident_counted is False


@pytest.mark.asyncio
async def test_live_business_tree_parity_is_unchanged(tmp_path: Path) -> None:
    live = tmp_path / "live"
    live.mkdir()
    (live / "story-state.json").write_text('{"revision":7}\n', encoding="utf-8")
    before = tree_manifest(live)
    wrapped, _ledger, _delegate, _latch = gateway(tmp_path / "canary")
    await run_boundaries(wrapped, 10)
    with pytest.raises(CanaryObservationGoalReachedStop):
        await wrapped.complete("planning", "s", "u", max_output_tokens=20)
    assert tree_manifest(live) == before


def test_c0b_smoke_profile_has_no_observation_goal_stop() -> None:
    profile = approval_profile("c0b_smoke_1")
    assert "target_strict_tool_shape_exact_captured" not in profile.stop_condition_policy
    assert STOP_OUTCOME not in profile.workflow_outcomes


def test_budget_counterfactual_profile_remains_disabled() -> None:
    profile = approval_profile("pa_strict_tool_obs_1")
    flags = dict(profile.required_feature_flags)
    assert flags["NOVEL_PA_OUTPUT_BUDGET_LINEAGE_V1"] is False
    assert "NOVEL_PA_OUTPUT_BUDGET_LINEAGE_V1" in profile.forbidden_feature_flags


@pytest.mark.asyncio
async def test_target_boundary_exception_does_not_reopen_goal(tmp_path: Path) -> None:
    wrapped, ledger, delegate, latch = gateway(
        tmp_path, target_call=1, fail_after_target=True,
    )
    first = asyncio.create_task(wrapped.complete(
        "planning", "system", "user", max_output_tokens=20,
    ))
    await wrapped.run_initial_preflight()
    with pytest.raises(RuntimeError, match="current_boundary_business_failure"):
        await first
    assert latch.reached is True
    assert wrapped.boundary_ledger[-1]["provider_observation"]["status"] == "failed"
    assert ledger.snapshot()["reservation_count"] == 1
    assert delegate.network == 1


def test_goal_receipt_survives_later_process_exception(tmp_path: Path) -> None:
    receipt = tmp_path / "goal.json"
    latch = ObservationGoalLatch(receipt_path=receipt)
    latch.observe(exact_target())
    try:
        raise RuntimeError("later process exception")
    except RuntimeError:
        pass
    persisted = json.loads(receipt.read_text(encoding="utf-8"))
    assert persisted["observation_goal_reached"] is True
    assert persisted["first_exact_target"]["observation_sha256"] == h("observation")


def test_launcher_cancellation_shape_does_not_clear_goal(tmp_path: Path) -> None:
    latch = ObservationGoalLatch(receipt_path=tmp_path / "goal.json")
    latch.observe(exact_target())
    stop = CanaryObservationGoalReachedStop(blocked_boundary_ordinal=11)
    assert isinstance(stop, asyncio.CancelledError)
    assert latch.snapshot()["observation_goal_reached"] is True

