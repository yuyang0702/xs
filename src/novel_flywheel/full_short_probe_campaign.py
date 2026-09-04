"""Closed-world, offline-safe orchestration for the eight Full Short probes.

This module deliberately knows nothing about credentials, HTTP clients, providers, or
project storage.  Its only external seam is a caller-supplied single-dispatch callback.
The callback receives an immutable, hash-bound request and is invoked at most once per
case.  Durable storage can persist :meth:`FullShortProbeCampaign.snapshot` between
transitions and restore it with :meth:`FullShortProbeCampaign.restore`.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import base64
import hashlib
import hmac
import json
import math
import secrets
import time
from typing import Callable, Iterable, Mapping, Sequence


SCHEMA = "FullShortEightProbeCampaignV1"
STATE_SCHEMA = "FullShortEightProbeCampaignStateV1"
CASE_COUNT = 8
BLOCKED_SHAPE_COUNT = 111


class ProbeCampaignError(RuntimeError):
    """A stable, non-secret campaign contract failure."""


class NonceState(StrEnum):
    UNUSED = "UNUSED"
    RESERVED_PRE_CREDENTIAL = "RESERVED_PRE_CREDENTIAL"
    DISPATCH_ATTEMPTED = "DISPATCH_ATTEMPTED"
    PASS_CONSUMED = "PASS_CONSUMED"
    FAILED_CONSUMED = "FAILED_CONSUMED"
    AMBIGUOUS_CONSUMED = "AMBIGUOUS_CONSUMED"


class ProbeResultKind(StrEnum):
    PASS = "PASS"
    FAILED = "FAILED"
    AMBIGUOUS = "AMBIGUOUS"


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def canonical_sha256(domain: str, value: object) -> str:
    return hashlib.sha256(domain.encode("ascii") + b"\x00" + _canonical_bytes(value)).hexdigest()


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ProbeCampaignError(code)


def _hex64(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdef" for char in value)


@dataclass(frozen=True)
class ProbeRouteIdentity:
    provider: str
    operator: str
    destination_sha256: str
    protocol: str
    model: str
    route_fingerprint: str

    def __post_init__(self) -> None:
        _require(all((self.provider, self.operator, self.protocol, self.model)), "ROUTE_FIELD_EMPTY")
        _require(_hex64(self.destination_sha256), "DESTINATION_SHA256_INVALID")
        _require(_hex64(self.route_fingerprint), "ROUTE_FINGERPRINT_INVALID")


@dataclass(frozen=True)
class ProbeCase:
    ordinal: int
    case_id: str
    route: ProbeRouteIdentity
    fixture_sha256: str
    input_envelope_sha256: str
    estimated_input_tokens: int
    wire_requested_output_cap: int
    blocked_shape_ordinals: tuple[int, ...]

    def __post_init__(self) -> None:
        _require(self.ordinal > 0 and bool(self.case_id), "CASE_IDENTITY_INVALID")
        _require(_hex64(self.fixture_sha256), "FIXTURE_SHA256_INVALID")
        _require(_hex64(self.input_envelope_sha256), "INPUT_ENVELOPE_SHA256_INVALID")
        _require(self.estimated_input_tokens > 0, "CASE_INPUT_TOKENS_INVALID")
        _require(self.wire_requested_output_cap > 0, "CASE_OUTPUT_CAP_INVALID")
        _require(bool(self.blocked_shape_ordinals), "CASE_SHAPE_COVERAGE_EMPTY")
        _require(
            tuple(sorted(set(self.blocked_shape_ordinals))) == self.blocked_shape_ordinals,
            "CASE_SHAPE_COVERAGE_NOT_CANONICAL",
        )

    @property
    def case_sha256(self) -> str:
        return canonical_sha256("full-short-probe-case-v1", asdict(self))


@dataclass(frozen=True)
class CampaignLimits:
    provider_requests: int = 144
    http_post_attempts: int = 144
    network_requests: int = 144
    input_tokens: int = 4_000_000
    generated_output_tokens: int = 2_000_000
    output_tokens_per_request: int = 32_000
    elapsed_seconds: float = 36_000.0

    def __post_init__(self) -> None:
        _require(all(value > 0 for value in asdict(self).values()), "CAMPAIGN_LIMIT_INVALID")


@dataclass(frozen=True)
class ProbeCampaignPlan:
    cases: tuple[ProbeCase, ...]
    source_blocked_shape_ordinals: tuple[int, ...]
    limits: CampaignLimits = CampaignLimits()

    def __post_init__(self) -> None:
        _require(len(self.cases) == CASE_COUNT, "PROBE_CASE_COUNT_NOT_EIGHT")
        _require(tuple(case.ordinal for case in self.cases) == tuple(range(1, 9)), "CASE_ORDER_INVALID")
        _require(len({case.case_id for case in self.cases}) == CASE_COUNT, "CASE_ID_DUPLICATE")
        _require(
            len(self.source_blocked_shape_ordinals) == BLOCKED_SHAPE_COUNT
            and tuple(sorted(set(self.source_blocked_shape_ordinals)))
            == self.source_blocked_shape_ordinals,
            "SOURCE_BLOCKED_SHAPE_SET_INVALID",
        )
        covered: list[int] = []
        for case in self.cases:
            _require(
                case.wire_requested_output_cap <= self.limits.output_tokens_per_request,
                "CASE_OUTPUT_CAP_EXCEEDS_GLOBAL_CAP",
            )
            covered.extend(case.blocked_shape_ordinals)
        _require(len(covered) == len(set(covered)), "BLOCKED_SHAPE_COVERAGE_OVERLAP")
        _require(
            set(covered) == set(self.source_blocked_shape_ordinals),
            "BLOCKED_SHAPE_COVERAGE_NOT_111",
        )
        _require(
            sum(case.estimated_input_tokens for case in self.cases) <= self.limits.input_tokens,
            "SEALED_PLAN_INPUT_EXCEEDS_GLOBAL_CAP",
        )

    @property
    def plan_sha256(self) -> str:
        return canonical_sha256("full-short-eight-probe-plan-v1", asdict(self))


@dataclass(frozen=True)
class DispatchRequest:
    plan_sha256: str
    case_sha256: str
    case: ProbeCase
    nonce_sha256: str


@dataclass(frozen=True)
class DispatchResult:
    kind: ProbeResultKind
    typed_code: str
    raw_response: bytes
    generated_output_tokens: int | None
    actual_input_tokens: int | None = None

    def __post_init__(self) -> None:
        _require(bool(self.typed_code), "RESULT_TYPED_CODE_EMPTY")
        _require(isinstance(self.raw_response, bytes), "RAW_RESPONSE_NOT_BYTES")
        _require(
            self.generated_output_tokens is None
            or self.generated_output_tokens >= 0,
            "RESULT_OUTPUT_TOKENS_INVALID",
        )
        _require(
            self.actual_input_tokens is None or self.actual_input_tokens >= 0,
            "RESULT_INPUT_TOKENS_INVALID",
        )


Dispatch = Callable[[DispatchRequest], DispatchResult]
Persist = Callable[[Mapping[str, object]], None]


class FullShortProbeCampaign:
    """Exactly-once state machine for one sealed eight-case campaign."""

    def __init__(
        self,
        plan: ProbeCampaignPlan,
        *,
        integrity_key: bytes,
        nonce_factory: Callable[[], str] | None = None,
        persist: Persist | None = None,
        clock: Callable[[], float] = time.monotonic,
        absolute_deadline_unix_seconds: float | None = None,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        _require(
            isinstance(integrity_key, bytes) and len(integrity_key) >= 32,
            "STATE_INTEGRITY_KEY_INVALID",
        )
        self.plan = plan
        self._integrity_key = integrity_key
        self._nonce_factory = nonce_factory or (lambda: secrets.token_hex(32))
        self._persist = persist or (lambda _snapshot: None)
        self._clock = clock
        _require(
            absolute_deadline_unix_seconds is None
            or (
                isinstance(absolute_deadline_unix_seconds, (int, float))
                and not isinstance(absolute_deadline_unix_seconds, bool)
                and math.isfinite(float(absolute_deadline_unix_seconds))
                and float(absolute_deadline_unix_seconds) > 0
            ),
            "ABSOLUTE_DEADLINE_INVALID",
        )
        self._absolute_deadline_unix_seconds = (
            None
            if absolute_deadline_unix_seconds is None
            else float(absolute_deadline_unix_seconds)
        )
        self._wall_clock = wall_clock
        self._started = clock()
        self._records = [self._empty_record(case) for case in plan.cases]
        self._counters = {
            "provider_requests": 0,
            "http_post_attempts": 0,
            "network_requests": 0,
            "input_tokens": 0,
            "generated_output_tokens": 0,
            "elapsed_seconds": 0.0,
        }
        self._halt_code: str | None = None

    @staticmethod
    def _empty_record(case: ProbeCase) -> dict[str, object]:
        return {
            "ordinal": case.ordinal,
            "case_id": case.case_id,
            "case_sha256": case.case_sha256,
            "state": NonceState.UNUSED.value,
            "nonce_sha256": None,
            "typed_code": None,
            "raw_response_base64": None,
            "raw_response_sha256": None,
            "debited_input_tokens": 0,
            "debited_output_tokens": 0,
            "usage_debit_source": None,
        }

    @property
    def halted(self) -> bool:
        return self._halt_code is not None

    @property
    def counters(self) -> dict[str, int | float]:
        return dict(self._counters)

    @property
    def records(self) -> tuple[Mapping[str, object], ...]:
        return tuple(dict(record) for record in self._records)

    def _body(self) -> dict[str, object]:
        return {
            "schema": STATE_SCHEMA,
            "version": 1,
            "plan_sha256": self.plan.plan_sha256,
            "absolute_deadline_unix_seconds": (
                self._absolute_deadline_unix_seconds
            ),
            "records": self._records,
            "counters": self._counters,
            "halt_code": self._halt_code,
        }

    def snapshot(self) -> dict[str, object]:
        body = self._body()
        state_sha256 = canonical_sha256("full-short-eight-probe-state-v1", body)
        return {
            **json.loads(json.dumps(body)),
            "state_sha256": state_sha256,
            "state_hmac_sha256": hmac.new(
                self._integrity_key,
                b"full-short-eight-probe-state-hmac-v1\x00"
                + _canonical_bytes(body),
                hashlib.sha256,
            ).hexdigest(),
        }

    def _checkpoint(self) -> None:
        self._persist(self.snapshot())

    @classmethod
    def restore(
        cls,
        plan: ProbeCampaignPlan,
        snapshot: Mapping[str, object],
        **kwargs: object,
    ) -> "FullShortProbeCampaign":
        body = dict(snapshot)
        supplied_hmac = body.pop("state_hmac_sha256", None)
        supplied_sha = body.pop("state_sha256", None)
        _require(supplied_sha == canonical_sha256("full-short-eight-probe-state-v1", body), "STATE_SHA256_MISMATCH")
        integrity_key = kwargs.get("integrity_key")
        _require(
            isinstance(integrity_key, bytes) and len(integrity_key) >= 32,
            "STATE_INTEGRITY_KEY_INVALID",
        )
        expected_hmac = hmac.new(
            integrity_key,
            b"full-short-eight-probe-state-hmac-v1\x00" + _canonical_bytes(body),
            hashlib.sha256,
        ).hexdigest()
        _require(
            isinstance(supplied_hmac, str)
            and hmac.compare_digest(supplied_hmac, expected_hmac),
            "STATE_HMAC_MISMATCH",
        )
        _require(body.get("schema") == STATE_SCHEMA and body.get("version") == 1, "STATE_SCHEMA_INVALID")
        _require(body.get("plan_sha256") == plan.plan_sha256, "STATE_PLAN_SHA256_MISMATCH")
        campaign = cls(plan, **kwargs)
        records = body.get("records")
        counters = body.get("counters")
        _require(isinstance(records, list) and len(records) == CASE_COUNT, "STATE_RECORDS_INVALID")
        _require(isinstance(counters, dict), "STATE_COUNTERS_INVALID")
        campaign._records = [dict(record) for record in records if isinstance(record, dict)]
        _require(len(campaign._records) == CASE_COUNT, "STATE_RECORDS_INVALID")
        campaign._counters = dict(counters)
        campaign._halt_code = body.get("halt_code") if isinstance(body.get("halt_code"), str) else None
        _require(
            body.get("absolute_deadline_unix_seconds")
            == campaign._absolute_deadline_unix_seconds,
            "STATE_ABSOLUTE_DEADLINE_MISMATCH",
        )
        campaign._validate_restored_state()
        return campaign

    def _validate_restored_state(self) -> None:
        expected = [self._empty_record(case) for case in self.plan.cases]
        seen_nonce: set[str] = set()
        non_unused_seen = False
        stop_seen = False
        for index, (record, empty) in enumerate(zip(self._records, expected, strict=True)):
            for key in ("ordinal", "case_id", "case_sha256"):
                _require(record.get(key) == empty[key], "STATE_CASE_BINDING_MISMATCH")
            try:
                state = NonceState(str(record.get("state")))
            except ValueError as exc:
                raise ProbeCampaignError("NONCE_STATE_INVALID") from exc
            if stop_seen:
                _require(state is NonceState.UNUSED, "STATE_AFTER_TERMINAL_NOT_UNUSED")
            debited_input = record.get("debited_input_tokens")
            debited_output = record.get("debited_output_tokens")
            debit_source = record.get("usage_debit_source")
            _require(
                type(debited_input) is int and debited_input >= 0
                and type(debited_output) is int and debited_output >= 0,
                "STATE_USAGE_DEBIT_INVALID",
            )
            if state is NonceState.UNUSED:
                _require(
                    debited_input == debited_output == 0
                    and debit_source is None,
                    "STATE_UNUSED_DEBIT_INVALID",
                )
                stop_seen = True
                continue
            non_unused_seen = True
            nonce_sha = record.get("nonce_sha256")
            _require(isinstance(nonce_sha, str) and _hex64(nonce_sha), "NONCE_SHA256_INVALID")
            _require(nonce_sha not in seen_nonce, "NONCE_REUSED")
            seen_nonce.add(nonce_sha)
            if state in {NonceState.RESERVED_PRE_CREDENTIAL, NonceState.DISPATCH_ATTEMPTED}:
                if state is NonceState.RESERVED_PRE_CREDENTIAL:
                    _require(
                        debited_input == debited_output == 0
                        and debit_source is None,
                        "STATE_RESERVED_DEBIT_INVALID",
                    )
                else:
                    case = self.plan.cases[index]
                    _require(
                        debited_input == case.estimated_input_tokens
                        and debited_output == case.wire_requested_output_cap
                        and debit_source
                        == "AUTHORIZED_ESTIMATE_AND_FULL_OUTPUT_RESERVE",
                        "STATE_ATTEMPT_DEBIT_INVALID",
                    )
                self._halt_code = "INTERRUPTED_NONCE_FAIL_CLOSED"
                stop_seen = True
            elif state in {NonceState.FAILED_CONSUMED, NonceState.AMBIGUOUS_CONSUMED}:
                self._halt_code = "FIRST_DISPATCHED_FAILURE"
                stop_seen = True
            elif state is not NonceState.PASS_CONSUMED:
                raise ProbeCampaignError("NONCE_STATE_INVALID")
            if state.value.endswith("_CONSUMED"):
                encoded = record.get("raw_response_base64")
                _require(isinstance(encoded, str), "RAW_RESPONSE_CAPTURE_MISSING")
                raw = base64.b64decode(encoded, validate=True)
                _require(hashlib.sha256(raw).hexdigest() == record.get("raw_response_sha256"), "RAW_RESPONSE_CAPTURE_TAMPERED")
        _require(non_unused_seen or all(r["state"] == NonceState.UNUSED for r in self._records), "STATE_SEQUENCE_INVALID")
        attempted = sum(record["state"] in {
            NonceState.DISPATCH_ATTEMPTED.value,
            NonceState.PASS_CONSUMED.value,
            NonceState.FAILED_CONSUMED.value,
            NonceState.AMBIGUOUS_CONSUMED.value,
        } for record in self._records)
        for name in ("provider_requests", "http_post_attempts", "network_requests"):
            _require(self._counters.get(name) == attempted, "COUNTER_DISPATCH_MISMATCH")
        _require(
            self._counters.get("input_tokens")
            == sum(int(record.get("debited_input_tokens", -1)) for record in self._records),
            "COUNTER_INPUT_DEBIT_MISMATCH",
        )
        _require(
            self._counters.get("generated_output_tokens")
            == sum(int(record.get("debited_output_tokens", -1)) for record in self._records),
            "COUNTER_OUTPUT_DEBIT_MISMATCH",
        )

    def _check_caps(self, case: ProbeCase) -> None:
        limits = self.plan.limits
        projected = {
            "provider_requests": self._counters["provider_requests"] + 1,
            "http_post_attempts": self._counters["http_post_attempts"] + 1,
            "network_requests": self._counters["network_requests"] + 1,
            "input_tokens": self._counters["input_tokens"] + case.estimated_input_tokens,
        }
        for key, value in projected.items():
            _require(value <= getattr(limits, key), f"GLOBAL_{key.upper()}_CAP")
        _require(case.wire_requested_output_cap <= limits.output_tokens_per_request, "PER_REQUEST_OUTPUT_CAP")
        _require(
            self._counters["generated_output_tokens"]
            + case.wire_requested_output_cap
            <= limits.generated_output_tokens,
            "GLOBAL_GENERATED_OUTPUT_TOKENS_CAP",
        )
        _require(self._elapsed() <= limits.elapsed_seconds, "GLOBAL_ELAPSED_SECONDS_CAP")
        self.require_absolute_deadline()

    def require_absolute_deadline(self) -> None:
        """Reject an expired outer deadline before any irreversible boundary."""

        if self._absolute_deadline_unix_seconds is None:
            return
        now = float(self._wall_clock())
        _require(math.isfinite(now), "ABSOLUTE_DEADLINE_CLOCK_INVALID")
        _require(
            now < self._absolute_deadline_unix_seconds,
            "CAMPAIGN_ABSOLUTE_DEADLINE_EXPIRED",
        )

    def _elapsed(self) -> float:
        return float(self._counters["elapsed_seconds"]) + max(0.0, self._clock() - self._started)

    def run(self, dispatch: Dispatch) -> dict[str, object]:
        _require(not self.halted, self._halt_code or "CAMPAIGN_HALTED")
        for index, case in enumerate(self.plan.cases):
            record = self._records[index]
            if record["state"] == NonceState.PASS_CONSUMED.value:
                continue
            _require(record["state"] == NonceState.UNUSED.value, "NONCE_NOT_UNUSED")
            self._check_caps(case)
            nonce = self._nonce_factory()
            _require(isinstance(nonce, str) and bool(nonce), "NONCE_FACTORY_INVALID")
            nonce_sha = canonical_sha256("full-short-probe-nonce-v1", nonce)
            _require(nonce_sha not in {r.get("nonce_sha256") for r in self._records}, "NONCE_REUSED")
            record.update(state=NonceState.RESERVED_PRE_CREDENTIAL.value, nonce_sha256=nonce_sha)
            self._checkpoint()

            # Reservation is the last local transition before caller-owned credential lookup.
            record["state"] = NonceState.DISPATCH_ATTEMPTED.value
            for name in ("provider_requests", "http_post_attempts", "network_requests"):
                self._counters[name] += 1
            self._counters["input_tokens"] += case.estimated_input_tokens
            self._counters["generated_output_tokens"] += case.wire_requested_output_cap
            record.update(
                debited_input_tokens=case.estimated_input_tokens,
                debited_output_tokens=case.wire_requested_output_cap,
                usage_debit_source="AUTHORIZED_ESTIMATE_AND_FULL_OUTPUT_RESERVE",
            )
            self._checkpoint()
            request = DispatchRequest(self.plan.plan_sha256, case.case_sha256, case, nonce_sha)
            try:
                result = dispatch(request)
                _require(isinstance(result, DispatchResult), "DISPATCH_RESULT_INVALID")
            except BaseException:
                result = DispatchResult(
                    ProbeResultKind.AMBIGUOUS, "dispatch.interrupted", b"",
                    None, None,
                )

            conservative_debit = (
                result.kind is ProbeResultKind.AMBIGUOUS
                or result.actual_input_tokens is None
                or result.generated_output_tokens is None
            )
            debited_input = (
                case.estimated_input_tokens
                if conservative_debit
                else max(case.estimated_input_tokens, result.actual_input_tokens)
            )
            debited_output = (
                case.wire_requested_output_cap
                if conservative_debit else result.generated_output_tokens
            )
            assert debited_input is not None and debited_output is not None
            self._counters["input_tokens"] += (
                debited_input - int(record["debited_input_tokens"])
            )
            self._counters["generated_output_tokens"] += (
                debited_output - int(record["debited_output_tokens"])
            )
            record.update(
                debited_input_tokens=debited_input,
                debited_output_tokens=debited_output,
                usage_debit_source=(
                    "AUTHORIZED_ESTIMATE_AND_FULL_OUTPUT_RESERVE"
                    if conservative_debit
                    else "MAX_AUTHORIZED_ESTIMATE_PROVIDER_REPORTED_ACTUAL"
                ),
            )

            raw_sha = hashlib.sha256(result.raw_response).hexdigest()
            record.update(
                state={
                    ProbeResultKind.PASS: NonceState.PASS_CONSUMED.value,
                    ProbeResultKind.FAILED: NonceState.FAILED_CONSUMED.value,
                    ProbeResultKind.AMBIGUOUS: NonceState.AMBIGUOUS_CONSUMED.value,
                }[result.kind],
                typed_code=result.typed_code,
                raw_response_base64=base64.b64encode(result.raw_response).decode("ascii"),
                raw_response_sha256=raw_sha,
            )
            self._counters["elapsed_seconds"] = self._elapsed()
            self._started = self._clock()
            if (
                debited_output > case.wire_requested_output_cap
                or self._counters["input_tokens"] > self.plan.limits.input_tokens
                or self._counters["generated_output_tokens"] > self.plan.limits.generated_output_tokens
                or self._counters["elapsed_seconds"] > self.plan.limits.elapsed_seconds
            ):
                record["state"] = NonceState.FAILED_CONSUMED.value
                record["typed_code"] = "campaign.cap_exceeded"
                self._halt_code = "FIRST_DISPATCHED_FAILURE"
            elif result.kind is not ProbeResultKind.PASS:
                self._halt_code = "FIRST_DISPATCHED_FAILURE"
            self._checkpoint()
            if self.halted:
                break
        return self.snapshot()


def build_probe_campaign_plan(
    cases: Iterable[ProbeCase],
    limits: CampaignLimits | None = None,
    *,
    source_blocked_shape_ordinals: Iterable[int],
) -> ProbeCampaignPlan:
    """Build and validate the canonical closed-world plan."""

    return ProbeCampaignPlan(
        tuple(cases), tuple(source_blocked_shape_ordinals),
        limits or CampaignLimits(),
    )


__all__ = [
    "BLOCKED_SHAPE_COUNT", "CASE_COUNT", "CampaignLimits", "DispatchRequest",
    "DispatchResult", "FullShortProbeCampaign", "NonceState", "ProbeCampaignError",
    "ProbeCampaignPlan", "ProbeCase", "ProbeResultKind", "ProbeRouteIdentity",
    "build_probe_campaign_plan", "canonical_sha256",
]
