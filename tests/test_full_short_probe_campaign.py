from __future__ import annotations

import copy
import hashlib

import pytest

from novel_flywheel.full_short_probe_campaign import (
    CampaignLimits,
    DispatchResult,
    FullShortProbeCampaign,
    NonceState,
    ProbeCampaignError,
    ProbeCase,
    ProbeResultKind,
    ProbeRouteIdentity,
    build_probe_campaign_plan,
    canonical_sha256,
)


STATE_KEY = b"offline-probe-state-integrity-key-32-bytes"


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _plan(*, input_tokens: int = 10, output_cap: int = 20):
    buckets = (14, 14, 14, 14, 14, 14, 14, 13)
    cursor = 1
    cases = []
    for ordinal, size in enumerate(buckets, 1):
        shapes = tuple(range(cursor, cursor + size))
        cursor += size
        cases.append(ProbeCase(
            ordinal=ordinal,
            case_id=f"probe-{ordinal}",
            route=ProbeRouteIdentity(
                provider=f"provider-{ordinal}", operator=f"operator-{ordinal}",
                destination_sha256=_sha(f"destination-{ordinal}"), protocol="synthetic-v1",
                model=f"model-{ordinal}", route_fingerprint=_sha(f"route-{ordinal}"),
            ),
            fixture_sha256=_sha(f"fixture-{ordinal}"),
            input_envelope_sha256=_sha(f"envelope-{ordinal}"),
            estimated_input_tokens=input_tokens,
            wire_requested_output_cap=output_cap,
            blocked_shape_ordinals=shapes,
        ))
    return build_probe_campaign_plan(
        cases, source_blocked_shape_ordinals=range(1, 112),
    )


def test_all_eight_cases_cover_exactly_111_shapes_and_dispatch_once() -> None:
    seen = []
    persisted = []
    campaign = FullShortProbeCampaign(
        _plan(), integrity_key=STATE_KEY,
        nonce_factory=(f"nonce-{n}" for n in range(8)).__next__,
        persist=lambda snapshot: persisted.append(copy.deepcopy(snapshot)),
    )

    def dispatch(request):
        seen.append(request)
        return DispatchResult(ProbeResultKind.PASS, "probe.accepted", f"raw-{request.case.ordinal}".encode(), 3, 10)

    result = campaign.run(dispatch)
    assert [item.case.ordinal for item in seen] == list(range(1, 9))
    assert len({item.nonce_sha256 for item in seen}) == 8
    assert {shape for case in campaign.plan.cases for shape in case.blocked_shape_ordinals} == set(range(1, 112))
    assert campaign.counters["provider_requests"] == 8
    assert campaign.counters["http_post_attempts"] == 8
    assert campaign.counters["network_requests"] == 8
    assert campaign.counters["input_tokens"] == 80
    assert campaign.counters["generated_output_tokens"] == 24
    assert all(record["state"] == NonceState.PASS_CONSUMED for record in result["records"])
    assert all(record["raw_response_sha256"] for record in result["records"])
    assert len(persisted) == 24  # reserve, attempt, consume for each case


@pytest.mark.parametrize("kind", [ProbeResultKind.FAILED, ProbeResultKind.AMBIGUOUS])
def test_first_dispatched_failure_consumes_nonce_and_stops_without_retry(kind) -> None:
    calls = []
    campaign = FullShortProbeCampaign(_plan(), integrity_key=STATE_KEY, nonce_factory=(f"n-{n}" for n in range(8)).__next__)

    def dispatch(request):
        calls.append(request.case.ordinal)
        if request.case.ordinal == 3:
            return DispatchResult(kind, "probe.terminal", b"captured", 1, 10)
        return DispatchResult(ProbeResultKind.PASS, "probe.accepted", b"ok", 1, 10)

    state = campaign.run(dispatch)
    assert calls == [1, 2, 3]
    assert state["records"][2]["state"] == f"{kind.value}_CONSUMED"
    assert all(record["state"] == NonceState.UNUSED for record in state["records"][3:])
    with pytest.raises(ProbeCampaignError, match="FIRST_DISPATCHED_FAILURE"):
        campaign.run(dispatch)


def test_dispatch_exception_is_ambiguous_consumed_and_never_retried() -> None:
    campaign = FullShortProbeCampaign(_plan(), integrity_key=STATE_KEY, nonce_factory=lambda: "single-nonce")
    state = campaign.run(lambda _request: (_ for _ in ()).throw(ConnectionError("private detail")))
    assert state["records"][0]["state"] == NonceState.AMBIGUOUS_CONSUMED
    assert state["records"][0]["typed_code"] == "dispatch.interrupted"
    assert campaign.counters["network_requests"] == 1
    assert campaign.counters["input_tokens"] == 10
    assert campaign.counters["generated_output_tokens"] == 20
    assert state["records"][0]["usage_debit_source"] == (
        "AUTHORIZED_ESTIMATE_AND_FULL_OUTPUT_RESERVE"
    )


def test_missing_provider_usage_debits_authorized_upper_bounds() -> None:
    campaign = FullShortProbeCampaign(
        _plan(), integrity_key=STATE_KEY, nonce_factory=lambda: "missing-usage",
    )
    state = campaign.run(
        lambda _request: DispatchResult(
            ProbeResultKind.FAILED, "probe.usage_missing", b"captured",
            None, None,
        )
    )
    assert campaign.counters["input_tokens"] == 10
    assert campaign.counters["generated_output_tokens"] == 20
    assert state["records"][0]["debited_input_tokens"] == 10
    assert state["records"][0]["debited_output_tokens"] == 20
    assert state["records"][0]["usage_debit_source"] == (
        "AUTHORIZED_ESTIMATE_AND_FULL_OUTPUT_RESERVE"
    )
    assert "private detail" not in str(state)


def test_restart_after_attempt_fails_closed_without_redispatch() -> None:
    checkpoints = []
    campaign = FullShortProbeCampaign(
        _plan(), integrity_key=STATE_KEY, nonce_factory=lambda: "nonce", persist=lambda value: checkpoints.append(copy.deepcopy(value)),
    )
    campaign.run(lambda _request: DispatchResult(ProbeResultKind.FAILED, "failed", b"x", 0, 10))
    interrupted = checkpoints[1]  # durable DISPATCH_ATTEMPTED transition
    restored = FullShortProbeCampaign.restore(
        _plan(), interrupted, integrity_key=STATE_KEY,
    )
    assert restored.halted
    with pytest.raises(ProbeCampaignError, match="INTERRUPTED_NONCE_FAIL_CLOSED"):
        restored.run(lambda _request: pytest.fail("must not redispatch"))


def test_state_and_plan_tamper_fail_before_dispatch() -> None:
    plan = _plan()
    state = FullShortProbeCampaign(plan, integrity_key=STATE_KEY).snapshot()
    tampered = copy.deepcopy(state)
    tampered["counters"]["network_requests"] = 1
    with pytest.raises(ProbeCampaignError, match="STATE_SHA256_MISMATCH"):
        FullShortProbeCampaign.restore(plan, tampered, integrity_key=STATE_KEY)

    changed_cases = list(plan.cases)
    changed_cases[0] = ProbeCase(**{**changed_cases[0].__dict__, "fixture_sha256": _sha("tampered")})
    changed_plan = build_probe_campaign_plan(
        changed_cases, source_blocked_shape_ordinals=range(1, 112),
    )
    with pytest.raises(ProbeCampaignError, match="STATE_PLAN_SHA256_MISMATCH"):
        FullShortProbeCampaign.restore(
            changed_plan, state, integrity_key=STATE_KEY,
        )


def test_self_consistent_rewind_to_unused_is_rejected_by_keyed_anchor() -> None:
    plan = _plan()
    campaign = FullShortProbeCampaign(
        plan, integrity_key=STATE_KEY, nonce_factory=lambda: "consumed-nonce",
    )
    consumed = campaign.run(
        lambda _request: DispatchResult(
            ProbeResultKind.FAILED, "probe.terminal", b"captured", 1, 10,
        )
    )
    forged = copy.deepcopy(consumed)
    empty = FullShortProbeCampaign(plan, integrity_key=STATE_KEY).snapshot()
    forged.update({
        "records": empty["records"],
        "counters": empty["counters"],
        "halt_code": None,
    })
    forged_body = {
        key: value for key, value in forged.items()
        if key not in {"state_sha256", "state_hmac_sha256"}
    }
    forged["state_sha256"] = canonical_sha256(
        "full-short-eight-probe-state-v1", forged_body,
    )
    # An attacker can recompute the public digest but cannot mint the MAC.
    with pytest.raises(ProbeCampaignError, match="STATE_HMAC_MISMATCH"):
        FullShortProbeCampaign.restore(
            plan, forged, integrity_key=STATE_KEY,
        )


def test_invalid_coverage_overlap_and_global_cap_fail_closed() -> None:
    cases = list(_plan().cases)
    cases[-1] = ProbeCase(**{**cases[-1].__dict__, "blocked_shape_ordinals": (98,) + cases[-1].blocked_shape_ordinals})
    with pytest.raises(ProbeCampaignError, match="COVERAGE_OVERLAP"):
        build_probe_campaign_plan(
            cases, source_blocked_shape_ordinals=range(1, 112),
        )

    with pytest.raises(ProbeCampaignError, match="SEALED_PLAN_INPUT_EXCEEDS_GLOBAL_CAP"):
        build_probe_campaign_plan(
            _plan().cases, CampaignLimits(input_tokens=79),
            source_blocked_shape_ordinals=range(1, 112),
        )


def test_absolute_outer_deadline_stops_before_later_nonce_credential_or_http() -> None:
    class AdvancingClock:
        now = 100.0

        def __call__(self) -> float:
            return self.now

    clock = AdvancingClock()
    credentials = []
    http_posts = []
    campaign = FullShortProbeCampaign(
        _plan(), integrity_key=STATE_KEY,
        nonce_factory=(f"deadline-nonce-{n}" for n in range(8)).__next__,
        absolute_deadline_unix_seconds=105.0,
        wall_clock=clock,
    )

    def dispatch(request):
        credentials.append(request.case.ordinal)
        http_posts.append(request.case.ordinal)
        clock.now = 105.0
        return DispatchResult(
            ProbeResultKind.PASS, "probe.accepted", b"ok", 1, 10,
        )

    with pytest.raises(
        ProbeCampaignError, match="CAMPAIGN_ABSOLUTE_DEADLINE_EXPIRED",
    ):
        campaign.run(dispatch)

    assert credentials == http_posts == [1]
    assert campaign.records[0]["state"] == NonceState.PASS_CONSUMED
    assert campaign.records[1]["state"] == NonceState.UNUSED
    assert campaign.records[1]["nonce_sha256"] is None
