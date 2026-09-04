"""Production-derived fixtures and guarded dispatch for eight Full Short probes.

The module reads only the sealed 183-row capacity matrix and public provider
registry metadata while building fixtures.  Synthetic requests pass through
the production Anthropic payload projection.  The default runner replaces the
paid boundary with a deterministic in-memory callback; the separately named
keyring entrypoint is the only path that resolves credentials and dispatches.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import base64
import hashlib
import json
from pathlib import Path
import time
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlsplit

import httpx
from jsonschema import Draft202012Validator

from novel_flywheel.context_policy import estimate_input_tokens
from novel_flywheel.domain.models import (
    Message, ModelRequest, ModelResponse, ToolDefinition,
)
from novel_flywheel.external_workload_evidence import (
    ExpectedWorkloadEvidenceV1,
    VerifiedWorkloadEvidenceV1,
    deterministic_promotion_mapping_v1,
    seal_external_workload_evidence_v1,
    validate_external_workload_evidence_v1,
)
from novel_flywheel.full_short_probe_campaign import (
    CampaignLimits,
    DispatchResult,
    FullShortProbeCampaign,
    ProbeCase,
    ProbeResultKind,
    ProbeRouteIdentity,
    build_probe_campaign_plan,
)
from novel_flywheel.full_short_execution import (
    full_short_workload_partition_sha256_v1,
)
from novel_flywheel.generated_artifacts import (
    ARTIFACT_CONTRACT_REGISTRY,
    registered_business_wire_schema,
)
from novel_flywheel.provider_payloads import anthropic_payload_v1
from novel_flywheel.provider_response_capture import (
    ProviderResponseCaptureError,
    extract_provider_reported_actual_usage_v1,
)
from novel_flywheel.providers.http import SingleDispatchTransportPolicyV1
from novel_flywheel.providers.registry import ProviderRegistry


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
AUTHORITATIVE_MATRIX_PATH = REPOSITORY_ROOT / (
    "docs/superpowers/reports/full-short-capacity-final-one-round-confirmation-v1/"
    "exact-ready-authoritative-physical-attempt-matrix-v1.json"
)
AUTHORITATIVE_MATRIX_SHA256 = (
    "b8a49e188b0b13187e8730cbbbd48714fdb71a6aa5a16bd4f3ee25edf61e0287"
)
AUTHORITATIVE_SHAPE_COUNT = 183
BLOCKED_SHAPE_COUNT = 111
EXACT_PROBE_INPUT_TOKENS = 186_733
RELAY_OPERATOR = "THIRD_PARTY_RELAY_UNVERIFIED_UPSTREAM"


class CampaignFixtureError(RuntimeError):
    """A stable fail-closed error at the offline fixture boundary."""


@dataclass(frozen=True)
class ProbeFamilyDefinition:
    ordinal: int
    family_id: str
    role: str
    contract_name: str | None
    provider_id_sha256: str
    model: str
    protocol: str
    destination_sha256: str
    route_fingerprint: str
    blocked_shape_ordinals: tuple[int, ...]
    estimated_input_tokens: int
    wire_requested_output_cap: int


@dataclass(frozen=True)
class BoundPublicRoute:
    provider_id: str
    model_id: str
    provider: str
    operator: str
    destination: str
    protocol: str
    model: str
    route_fingerprint: str

    @property
    def probe_identity(self) -> ProbeRouteIdentity:
        return ProbeRouteIdentity(
            provider=self.provider,
            operator=self.operator,
            destination_sha256=hashlib.sha256(
                self.destination.encode("utf-8")
            ).hexdigest(),
            protocol=self.protocol,
            model=self.model,
            route_fingerprint=self.route_fingerprint,
        )


@dataclass(frozen=True)
class SyntheticProbeFixture:
    definition: ProbeFamilyDefinition
    route: BoundPublicRoute
    request: ModelRequest
    payload: Mapping[str, Any]
    payload_bytes: bytes
    request_family_sha256: str
    request_sha256: str
    fixture_sha256: str
    case: ProbeCase


@dataclass(frozen=True)
class OfflineFakeCampaignResult:
    campaign_state: Mapping[str, Any]
    raw_responses: tuple[bytes, ...]
    sealed_evidence: tuple[bytes, ...]
    verified_evidence: tuple[VerifiedWorkloadEvidenceV1, ...]
    promoted_evidence: Mapping[str, Mapping[str, Any]]
    external_action_counters: Mapping[str, int]
    privacy_counts: Mapping[str, int]


@dataclass(frozen=True)
class GuardedRealCampaignResult:
    """Captured result of an explicitly authorized production-bound run."""

    campaign_state: Mapping[str, Any]
    raw_responses: tuple[bytes, ...]
    sealed_evidence: tuple[bytes, ...]
    verified_evidence: tuple[VerifiedWorkloadEvidenceV1, ...]
    promoted_evidence: Mapping[str, Mapping[str, Any]]
    transport_counters: Mapping[str, int]
    privacy_counts: Mapping[str, int]


_FAMILY_RULES: tuple[tuple[str, str, str | None], ...] = (
    ("draft_plain", "draft", None),
    ("polish_plain", "polish", None),
    ("planning_adaptation", "planning", "planning_event_realizations"),
    ("causal_chain", "planning", "short_causal_chain"),
    ("execution_manifest", "planning", "execution_manifest"),
    ("final_review_window", "final_review", "final_review_window"),
    ("final_review_adjudication", "final_review", "full_short_final_review"),
    ("maintenance_plain", "maintenance", None),
)


def _fail(code: str) -> None:
    raise CampaignFixtureError(code)


def _family_key(item: Mapping[str, Any]) -> str:
    role = item.get("role")
    stage = str(item.get("stage") or "")
    if role == "draft" and stage.startswith("draft-part-"):
        return "draft_plain"
    if role == "polish" and stage.startswith("polish-part-"):
        return "polish_plain"
    if role == "planning" and stage.startswith("planning-adaptation-segment-"):
        return "planning_adaptation"
    if role == "planning" and stage.startswith("planning-causal-chain-packet-"):
        return "causal_chain"
    if role == "planning" and stage.startswith("planning-execution-segment-"):
        return "execution_manifest"
    if role == "final_review" and stage.startswith("final_review-window-"):
        return "final_review_window"
    if role == "final_review" and stage == "final_review-adjudication":
        return "final_review_adjudication"
    if role == "maintenance" and stage.startswith("maintenance-map-"):
        return "maintenance_plain"
    _fail("BLOCKED_SHAPE_FAMILY_UNKNOWN")


def load_authoritative_matrix(
    path: Path = AUTHORITATIVE_MATRIX_PATH,
) -> Mapping[str, Any]:
    """Load the exact sealed matrix; a successor matrix needs explicit review."""

    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != AUTHORITATIVE_MATRIX_SHA256:
        _fail("AUTHORITATIVE_MATRIX_SHA256_MISMATCH")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        _fail("AUTHORITATIVE_MATRIX_INVALID_JSON")
    if not isinstance(value, dict):
        _fail("AUTHORITATIVE_MATRIX_INVALID")
    return value


def derive_probe_families(
    matrix: Mapping[str, Any] | None = None,
) -> tuple[ProbeFamilyDefinition, ...]:
    """Partition the sparse blocked ordinals and take each wire-family maximum."""

    source = matrix or load_authoritative_matrix()
    attempts = source.get("attempts")
    if (
        source.get("schema") != "ExactReadyAuthoritativePhysicalAttemptMatrixV1"
        or source.get("version") != 1
        or source.get("exact_ready_total_physical_attempt_shapes")
        != AUTHORITATIVE_SHAPE_COUNT
        or not isinstance(attempts, list)
        or len(attempts) != AUTHORITATIVE_SHAPE_COUNT
    ):
        _fail("AUTHORITATIVE_MATRIX_CONTRACT_MISMATCH")
    ordinals = [item.get("shape_ordinal") for item in attempts if isinstance(item, dict)]
    if ordinals != list(range(1, AUTHORITATIVE_SHAPE_COUNT + 1)):
        _fail("AUTHORITATIVE_MATRIX_ORDINALS_INVALID")
    blocked = [item for item in attempts if item.get("admission_result") == "BLOCKED"]
    if len(blocked) != BLOCKED_SHAPE_COUNT:
        _fail("AUTHORITATIVE_BLOCKED_SHAPE_COUNT_MISMATCH")

    grouped: dict[str, list[Mapping[str, Any]]] = {
        key: [] for key, _role, _contract in _FAMILY_RULES
    }
    for item in blocked:
        grouped[_family_key(item)].append(item)

    result: list[ProbeFamilyDefinition] = []
    for ordinal, (key, role, contract_name) in enumerate(_FAMILY_RULES, 1):
        members = grouped[key]
        if not members:
            _fail("PROBE_FAMILY_EMPTY")
        identity_fields = (
            "provider_id_sha256", "model", "protocol", "destination_sha256",
            "route_fingerprint",
        )
        identities = {
            tuple(str(item.get(field) or "") for field in identity_fields)
            for item in members
        }
        if len(identities) != 1 or any(not value for value in next(iter(identities))):
            _fail("PROBE_FAMILY_ROUTE_IDENTITY_AMBIGUOUS")
        identity = next(iter(identities))
        if contract_name is not None:
            registration = ARTIFACT_CONTRACT_REGISTRY.get(contract_name)
            if registration is None:
                _fail("STRUCTURED_SCHEMA_IDENTITY_UNAVAILABLE")
            try:
                registered_business_wire_schema(contract_name)
            except (KeyError, ValueError):
                _fail("STRUCTURED_SCHEMA_IDENTITY_UNAVAILABLE")
        result.append(ProbeFamilyDefinition(
            ordinal=ordinal,
            family_id=key,
            role=role,
            contract_name=contract_name,
            provider_id_sha256=identity[0],
            model=identity[1],
            protocol=identity[2],
            destination_sha256=identity[3],
            route_fingerprint=identity[4],
            blocked_shape_ordinals=tuple(
                sorted(int(item["shape_ordinal"]) for item in members)
            ),
            estimated_input_tokens=max(
                int(item["provider_wire_payload_estimated_tokens"])
                for item in members
            ),
            wire_requested_output_cap=max(
                int(item["provider_wire_requested_output_cap"])
                for item in members
            ),
        ))

    covered = tuple(sorted(
        shape for family in result for shape in family.blocked_shape_ordinals
    ))
    source_blocked = tuple(sorted(int(item["shape_ordinal"]) for item in blocked))
    if covered != source_blocked or len(set(covered)) != BLOCKED_SHAPE_COUNT:
        _fail("BLOCKED_SHAPE_COVERAGE_INVALID")
    if sum(item.estimated_input_tokens for item in result) != EXACT_PROBE_INPUT_TOKENS:
        _fail("PROBE_FAMILY_INPUT_MAXIMA_DRIFT")
    return tuple(result)


def _bind_public_route(registry: Any, family: ProbeFamilyDefinition) -> BoundPublicRoute:
    matches: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    for provider in registry.db.list_providers():
        provider_id = str(provider.get("id") or "")
        if hashlib.sha256(provider_id.encode("utf-8")).hexdigest() != family.provider_id_sha256:
            continue
        for model in registry.db.list_models(provider_id):
            if str(model.get("model_name") or "") == family.model:
                matches.append((provider, model))
    if len(matches) != 1:
        _fail("CURRENT_REGISTRY_ROUTE_NOT_UNIQUE")
    provider, model = matches[0]
    public = registry.inspect_public_route(str(provider["id"]), str(model["id"]))
    if (
        public.route_fingerprint != family.route_fingerprint
        or public.protocol != family.protocol
        # The sealed discovery matrix recorded the public provider base URL.
        # The current registry separately normalizes the physical dispatch
        # destination (including port and endpoint path).  Bind both instead
        # of applying the historical hash to the newer projection.
        or hashlib.sha256(
            str(public.provider.get("base_url") or "").rstrip("/").encode("utf-8")
        ).hexdigest() != family.destination_sha256
        or str(public.model.get("model_name") or "") != family.model
        or public.provider_operator != RELAY_OPERATOR
    ):
        _fail("CURRENT_REGISTRY_ROUTE_BINDING_MISMATCH")
    return BoundPublicRoute(
        provider_id=str(provider["id"]),
        model_id=str(model["id"]),
        provider=str(public.provider.get("name") or ""),
        operator=public.provider_operator,
        destination=public.destination,
        protocol=public.protocol,
        model=str(public.model.get("model_name") or ""),
        route_fingerprint=public.route_fingerprint,
    )


def _payload_bytes(request: ModelRequest) -> bytes:
    # Match the production httpx JSON serializer exactly. URL and headers do
    # not affect Request.content, so these are the precise authorized provider
    # payload bytes observed immediately before the network send.
    return httpx.Request(
        "POST", "https://synthetic.invalid/v1/messages",
        json=anthropic_payload_v1(request),
    ).content


def _deterministic_low_compressibility_ascii(
    *, family_id: str, length: int,
) -> str:
    """Return private-data-free filler without the token collapse of one run.

    Repeating one character satisfies the repository's coarse character-based
    estimator but can collapse to a tiny number of tokens in a Provider-owned
    tokenizer.  Domain-separated SHA-256 blocks encoded with the URL-safe
    alphabet remain deterministic and non-sensitive while exercising a much
    more conservative token shape.  The Provider-reported lower-bound check is
    still authoritative; this generator is not treated as a tokenizer oracle.
    """

    if type(length) is not int or length < 0 or not family_id:
        _fail("SYNTHETIC_FILLER_LENGTH_INVALID")
    chunks: list[str] = []
    produced = 0
    counter = 0
    domain = b"novel-flywheel-full-short-probe-filler-v1\x00"
    family = family_id.encode("ascii")
    while produced < length:
        digest = hashlib.sha256(
            domain + family + b"\x00" + counter.to_bytes(8, "big")
        ).digest()
        chunk = base64.urlsafe_b64encode(digest).decode("ascii")
        chunks.append(chunk)
        produced += len(chunk)
        counter += 1
    return "".join(chunks)[:length]


def _exact_dispatch_destination(url: str) -> str:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        return ""
    return (
        f"{parsed.scheme}://{parsed.hostname}:{parsed.port or 443}"
        f"{parsed.path}"
    )


def _synthetic_request(
    family: ProbeFamilyDefinition, route: BoundPublicRoute,
) -> tuple[ModelRequest, Mapping[str, Any], bytes]:
    system = f"SYNTHETIC PROBE SYSTEM {family.family_id}. PUBLIC ROUTE SHAPE ONLY."
    user_prefix = f"SYNTHETIC PROBE USER {family.family_id}. "
    tools: list[ToolDefinition] = []
    required_tool: str | None = None
    if family.contract_name is not None:
        schema = registered_business_wire_schema(family.contract_name)
        tools = [ToolDefinition(
            name=family.contract_name,
            description="Return the complete validated structured artifact.",
            input_schema=schema,
        )]
        required_tool = family.contract_name
    base = ModelRequest(
        model=route.model,
        messages=[
            Message(role="system", content=system),
            Message(role="user", content=user_prefix),
        ],
        max_output_tokens=family.wire_requested_output_cap,
        tools=tools,
        required_tool=required_tool,
    )
    base_bytes = _payload_bytes(base)
    target_ascii_length = family.estimated_input_tokens * 4
    padding = target_ascii_length - len(base_bytes)
    if padding < 0:
        _fail("SYNTHETIC_FIXTURE_CANNOT_FIT_WIRE_MAXIMUM")
    filler = _deterministic_low_compressibility_ascii(
        family_id=family.family_id, length=padding,
    )
    request = base.model_copy(update={
        "messages": [
            Message(role="system", content=system),
            Message(role="user", content=user_prefix + filler),
        ],
    })
    payload = anthropic_payload_v1(request)
    payload_bytes = _payload_bytes(request)
    if estimate_input_tokens(payload_bytes.decode("utf-8")) != family.estimated_input_tokens:
        _fail("SYNTHETIC_FIXTURE_WIRE_ESTIMATE_MISMATCH")
    if payload.get("max_tokens") != family.wire_requested_output_cap:
        _fail("SYNTHETIC_FIXTURE_OUTPUT_CAP_MISMATCH")
    return request, MappingProxyType(payload), payload_bytes


def build_synthetic_probe_fixtures(
    registry: Any,
    *,
    matrix: Mapping[str, Any] | None = None,
) -> tuple[SyntheticProbeFixture, ...]:
    """Bind the matrix families to current public registry routes and payloads."""

    fixtures: list[SyntheticProbeFixture] = []
    for definition in derive_probe_families(matrix):
        route = _bind_public_route(registry, definition)
        request, payload, payload_bytes = _synthetic_request(definition, route)
        request_sha256 = hashlib.sha256(payload_bytes).hexdigest()
        schema_sha256 = (
            hashlib.sha256(json.dumps(
                registered_business_wire_schema(definition.contract_name),
                ensure_ascii=False, allow_nan=False, sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")).hexdigest()
            if definition.contract_name is not None else None
        )
        structured = definition.contract_name is not None
        request_family_sha256 = full_short_workload_partition_sha256_v1(
            family_id=definition.family_id,
            provider=route.provider,
            operator=route.operator,
            destination=route.destination,
            protocol=route.protocol,
            model=route.model,
            route_fingerprint_sha256=route.route_fingerprint,
            contract_name=definition.contract_name if structured else None,
            contract_version=(
                ARTIFACT_CONTRACT_REGISTRY[definition.contract_name].version
                if structured else None
            ),
            contract_schema_sha256=schema_sha256 if structured else None,
        )
        fixture_bytes = json.dumps(
            request.model_dump(mode="json"), ensure_ascii=False, allow_nan=False,
            sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        fixture_sha256 = hashlib.sha256(fixture_bytes).hexdigest()
        case = ProbeCase(
            ordinal=definition.ordinal,
            case_id=f"full-short-probe-{definition.ordinal:02d}-{definition.family_id}",
            route=route.probe_identity,
            fixture_sha256=fixture_sha256,
            input_envelope_sha256=request_sha256,
            estimated_input_tokens=definition.estimated_input_tokens,
            wire_requested_output_cap=definition.wire_requested_output_cap,
            blocked_shape_ordinals=definition.blocked_shape_ordinals,
        )
        fixtures.append(SyntheticProbeFixture(
            definition=definition, route=route, request=request,
            payload=payload, payload_bytes=payload_bytes,
            request_family_sha256=request_family_sha256,
            request_sha256=request_sha256, fixture_sha256=fixture_sha256,
            case=case,
        ))
    return tuple(fixtures)


def _fake_response(fixture: SyntheticProbeFixture) -> bytes:
    if fixture.definition.contract_name is None:
        content = [{"type": "text", "text": "SYNTHETIC_ACCEPTED"}]
        stop_reason = "end_turn"
    else:
        content = [{
            "type": "tool_use",
            "id": f"synthetic-{fixture.definition.ordinal}",
            "name": fixture.definition.contract_name,
            "input": {"synthetic": "accepted"},
        }]
        stop_reason = "tool_use"
    return json.dumps({
        "content": content,
        "id": f"synthetic-response-{fixture.definition.ordinal}",
        "stop_reason": stop_reason,
        "usage": {
            "input_tokens": fixture.definition.estimated_input_tokens,
            "output_tokens": 1,
        },
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def run_offline_fake_campaign(
    fixtures: Sequence[SyntheticProbeFixture],
    *,
    authorization_sha256: str,
    final_execution_head: str,
    key_id: str,
    signing_key: bytes,
) -> OfflineFakeCampaignResult:
    """Run all fixtures with a zero-egress fake and seal exact captured bytes."""

    source_ordinals = tuple(sorted(
        ordinal
        for fixture in fixtures
        for ordinal in fixture.definition.blocked_shape_ordinals
    ))
    plan = build_probe_campaign_plan(
        (fixture.case for fixture in fixtures), CampaignLimits(),
        source_blocked_shape_ordinals=source_ordinals,
    )
    by_case_sha = {fixture.case.case_sha256: fixture for fixture in fixtures}
    if len(by_case_sha) != 8:
        _fail("SYNTHETIC_FIXTURE_CASE_IDENTITY_INVALID")
    dispatched: list[tuple[Any, SyntheticProbeFixture, bytes]] = []

    def fake_dispatch(dispatch_request: Any) -> DispatchResult:
        fixture = by_case_sha.get(dispatch_request.case_sha256)
        if fixture is None or fixture.case != dispatch_request.case:
            _fail("FAKE_DISPATCH_CASE_BINDING_MISMATCH")
        raw = _fake_response(fixture)
        dispatched.append((dispatch_request, fixture, raw))
        return DispatchResult(
            ProbeResultKind.PASS, "probe.synthetic.accepted", raw, 1,
            fixture.definition.estimated_input_tokens,
        )

    campaign = FullShortProbeCampaign(
        plan,
        integrity_key=signing_key,
        nonce_factory=(f"offline-synthetic-nonce-{n}" for n in range(1, 9)).__next__,
    )
    state = campaign.run(fake_dispatch)
    packages: list[bytes] = []
    verified: list[VerifiedWorkloadEvidenceV1] = []
    raw_responses: list[bytes] = []
    for (dispatch_request, fixture, raw), record in zip(
        dispatched, state["records"], strict=True,
    ):
        captured = base64.b64decode(str(record["raw_response_base64"]), validate=True)
        if captured != raw or hashlib.sha256(raw).hexdigest() != record["raw_response_sha256"]:
            _fail("FAKE_RESPONSE_CAPTURE_NOT_EXACT")
        expected = ExpectedWorkloadEvidenceV1(
            authorization_sha256=authorization_sha256,
            final_execution_head=final_execution_head,
            provider=fixture.route.provider,
            operator=fixture.route.operator,
            destination=fixture.route.destination,
            protocol=fixture.route.protocol,
            model=fixture.route.model,
            route_fingerprint_sha256=fixture.route.route_fingerprint,
            case_id=fixture.case.case_id,
            fixture_sha256=fixture.fixture_sha256,
            request_family_sha256=fixture.request_family_sha256,
            request_sha256=fixture.request_sha256,
            input_tokens=fixture.definition.estimated_input_tokens,
            requested_output_tokens=fixture.definition.wire_requested_output_cap,
            key_id=key_id,
        )
        evidence_payload = {
            "authorization_sha256": authorization_sha256,
            "case": {
                "case_id": fixture.case.case_id,
                "fixture_sha256": fixture.fixture_sha256,
            },
            "final_execution_head": final_execution_head,
            "nonce": {
                "dispatch_attempt_count": 1,
                "nonce_sha256": dispatch_request.nonce_sha256,
                "state": "CONSUMED",
            },
            "request": {
                "input_tokens": fixture.definition.estimated_input_tokens,
                "request_family_sha256": fixture.request_family_sha256,
                "request_sha256": fixture.request_sha256,
                "requested_output_tokens": fixture.definition.wire_requested_output_cap,
            },
            "result": {
                "actual_input_tokens": fixture.definition.estimated_input_tokens,
                "actual_output_tokens": 1,
                "complete": True,
                "input_accepted": True,
                "output_accepted": True,
                "response_sha256": hashlib.sha256(raw).hexdigest(),
                "terminal_status": "SUCCESS",
            },
            "route": {
                "destination": fixture.route.destination,
                "model": fixture.route.model,
                "operator": fixture.route.operator,
                "protocol": fixture.route.protocol,
                "provider": fixture.route.provider,
                "route_fingerprint_sha256": fixture.route.route_fingerprint,
            },
        }
        package = seal_external_workload_evidence_v1(
            evidence_payload, key_id=key_id, signing_key=signing_key,
        )
        packages.append(package)
        verified.append(validate_external_workload_evidence_v1(
            package, expected=expected, verification_keys={key_id: signing_key},
        ))
        raw_responses.append(raw)

    if len(dispatched) != 8:
        _fail("FAKE_CAMPAIGN_DID_NOT_DISPATCH_EIGHT")
    zero = MappingProxyType({
        "credential_lookups": 0,
        "provider_client_creations": 0,
        "provider_requests": 0,
        "http_post_attempts": 0,
        "network_calls": 0,
        "model_calls": 0,
        "paid_calls": 0,
        "real_full_short_executions": 0,
    })
    privacy = MappingProxyType({
        "RAW_NOVEL_CONTENT_EGRESS_COUNT": 0,
        "REAL_PROJECT_CONTENT_EGRESS_COUNT": 0,
    })
    return OfflineFakeCampaignResult(
        campaign_state=MappingProxyType(state),
        raw_responses=tuple(raw_responses),
        sealed_evidence=tuple(packages),
        verified_evidence=tuple(verified),
        promoted_evidence=deterministic_promotion_mapping_v1(verified),
        external_action_counters=zero,
        privacy_counts=privacy,
    )


class GuardedProviderDispatch:
    """One-route production adapter callback for the campaign state machine.

    Construction is inert.  ``ProviderRegistry.resolve`` (and therefore the
    credential read and provider-client construction) happens only after the
    campaign has durably reserved its nonce and invoked this callback.
    """

    def __init__(
        self, fixtures: Sequence[SyntheticProbeFixture], registry: ProviderRegistry,
        *, deadline_guard: Callable[[], None] | None = None,
    ) -> None:
        if registry.transport_policy != SingleDispatchTransportPolicyV1.phase_b():
            _fail("SINGLE_DISPATCH_TRANSPORT_POLICY_REQUIRED")
        if (
            registry.attempt_observer is not None
            and registry.attempt_observer is not self
        ):
            _fail("SINGLE_DISPATCH_OBSERVER_BINDING_REQUIRED")
        registry.attempt_observer = self
        self._registry = registry
        self._deadline_guard = deadline_guard or (lambda: None)
        self._fixtures = {fixture.case.case_sha256: fixture for fixture in fixtures}
        if len(self._fixtures) != 8:
            _fail("SYNTHETIC_FIXTURE_CASE_IDENTITY_INVALID")
        self._active: SyntheticProbeFixture | None = None
        self._raw_response: bytes | None = None
        self._response_complete = False
        self._status_code: int | None = None
        self._provider_reported_usage: Mapping[str, Any] | None = None
        self._case_http_posts = 0
        self._case_network_requests = 0
        self._total_http_posts = 0
        self._total_network_requests = 0
        self._input_tokens_by_case: dict[str, int] = {}
        self._output_tokens_by_case: dict[str, int] = {}

    @property
    def transport_counters(self) -> Mapping[str, int]:
        return MappingProxyType({
            "http_post_attempts": self._total_http_posts,
            "network_requests": self._total_network_requests,
        })

    @property
    def output_tokens_by_case(self) -> Mapping[str, int]:
        return MappingProxyType(dict(self._output_tokens_by_case))

    @property
    def input_tokens_by_case(self) -> Mapping[str, int]:
        return MappingProxyType(dict(self._input_tokens_by_case))

    def bind_route(
        self, *, role: str, lane: str, provider_id: str, model_id: str,
        route_fingerprint: str,
    ) -> None:
        # ProviderRegistry invokes this hook immediately before ``secrets.get``.
        # Recheck here, after the caller's public-route/DB scan, so time spent
        # revalidating the route cannot carry a credential read past the outer
        # campaign's absolute deadline.
        self._deadline_guard()
        fixture = self._require_active()
        if (
            role != fixture.definition.role
            or lane != "full_short_exact_probe"
            or provider_id != fixture.route.provider_id
            or model_id != fixture.route.model_id
            or route_fingerprint != fixture.route.route_fingerprint
        ):
            _fail("DISPATCH_ROUTE_SWITCH_REJECTED")

    def bind_model_request(self, *, protocol: str, request: ModelRequest) -> None:
        fixture = self._require_active()
        if protocol != fixture.route.protocol or request != fixture.request:
            _fail("DISPATCH_REQUEST_BINDING_MISMATCH")

    def before_http_dispatch(
        self, *, method: str, url: str, payload: Mapping[str, Any],
        request_bytes: bytes,
    ) -> None:
        self._deadline_guard()
        fixture = self._require_active()
        authorized_request_bytes = _payload_bytes(fixture.request)
        try:
            materialized = json.loads(request_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            _fail("DISPATCH_REQUEST_BYTES_INVALID")
        if (
            method != "POST"
            or not url
            or _exact_dispatch_destination(url) != fixture.route.destination
            or fixture.payload_bytes != authorized_request_bytes
            or request_bytes != authorized_request_bytes
            or materialized != dict(fixture.payload)
            or dict(payload) != dict(fixture.payload)
            or hashlib.sha256(request_bytes).hexdigest()
            != fixture.request_sha256
        ):
            _fail("DISPATCH_REQUEST_BINDING_MISMATCH")

    def before_http_post(self) -> None:
        self._deadline_guard()
        self._require_active()
        self._case_http_posts += 1
        self._total_http_posts += 1
        if self._case_http_posts != 1:
            _fail("SECOND_HTTP_POST_REJECTED")

    def before_network_request(self) -> None:
        self._deadline_guard()
        self._require_active()
        self._case_network_requests += 1
        self._total_network_requests += 1
        if self._case_network_requests != 1:
            _fail("SECOND_NETWORK_REQUEST_REJECTED")

    def capture_provider_protocol_input(
        self, *, data: bytes, status_code: int, content_type: str,
        encoding: str, transport_complete: bool,
    ) -> None:
        self._require_active()
        if self._raw_response is not None or not isinstance(data, bytes):
            _fail("MULTIPLE_PROVIDER_RESPONSES_REJECTED")
        self._raw_response = data
        self._status_code = status_code
        self._response_complete = bool(transport_complete)
        self._provider_reported_usage = None
        if transport_complete and 200 <= status_code < 300:
            try:
                self._provider_reported_usage = (
                    extract_provider_reported_actual_usage_v1(
                        data,
                        protocol=self._require_active().route.protocol,
                        content_type=content_type,
                        encoding=encoding,
                    )
                )
            except ProviderResponseCaptureError:
                # The enclosing dispatch classifies this case as a terminal
                # probe failure.  No unmetered response can promote capacity.
                self._provider_reported_usage = None

    def _require_active(self) -> SyntheticProbeFixture:
        if self._active is None:
            _fail("DISPATCH_OBSERVER_OUTSIDE_ACTIVE_CASE")
        return self._active

    @staticmethod
    async def _complete_and_close(adapter: Any, request: ModelRequest) -> ModelResponse:
        try:
            response = await adapter.complete(request)
        finally:
            client = getattr(adapter, "client", None)
            close = getattr(client, "aclose", None)
            if callable(close):
                await close()
        if not isinstance(response, ModelResponse):
            _fail("PROVIDER_RESPONSE_TYPE_INVALID")
        return response

    @staticmethod
    def _response_is_accepted(
        fixture: SyntheticProbeFixture, response: ModelResponse,
    ) -> bool:
        finish_reason = str(response.finish_reason or "").strip().casefold()
        if finish_reason in {"max_tokens", "length"}:
            return False
        if finish_reason not in {"end_turn", "stop_sequence", "tool_use"}:
            return False
        contract_name = fixture.definition.contract_name
        if contract_name is None:
            return bool(response.text.strip())
        if finish_reason != "tool_use" or len(response.tool_calls) != 1:
            return False
        tool_call = response.tool_calls[0]
        if tool_call.name != contract_name or not isinstance(tool_call.arguments, dict):
            return False
        schema = registered_business_wire_schema(contract_name)
        return Draft202012Validator(schema).is_valid(tool_call.arguments)

    def __call__(self, dispatch_request: Any) -> DispatchResult:
        fixture = self._fixtures.get(dispatch_request.case_sha256)
        if fixture is None or fixture.case != dispatch_request.case:
            _fail("REAL_DISPATCH_CASE_BINDING_MISMATCH")
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            _fail("REAL_DISPATCH_REQUIRES_SYNCHRONOUS_CALLER")

        # Re-read the absolute outer deadline before the credential boundary.
        # The state machine already checked it before reserving this case's
        # nonce; this second check closes the reservation-to-keyring gap.
        self._deadline_guard()

        # Re-read the exact public route immediately before the credential
        # boundary.  No scheduler or fallback selector participates.
        rebound = _bind_public_route(self._registry, fixture.definition)
        if rebound != fixture.route:
            _fail("CURRENT_REGISTRY_ROUTE_BINDING_MISMATCH")
        self._active = fixture
        self._raw_response = None
        self._response_complete = False
        self._status_code = None
        self._provider_reported_usage = None
        self._case_http_posts = 0
        self._case_network_requests = 0
        try:
            resolved = self._registry.resolve(
                fixture.route.provider_id, fixture.route.model_id,
                role=fixture.definition.role, lane="full_short_exact_probe",
            )
            if (
                resolved.provider_id != fixture.route.provider_id
                or resolved.model_id != fixture.route.model_id
                or resolved.model_name != fixture.route.model
                or resolved.protocol != fixture.route.protocol
                or resolved.destination != fixture.route.destination
                or resolved.route_fingerprint != fixture.route.route_fingerprint
                or resolved.provider_operator != fixture.route.operator
            ):
                _fail("RESOLVED_ROUTE_SWITCH_REJECTED")
            response = asyncio.run(
                self._complete_and_close(resolved.adapter, fixture.request)
            )
            content_accepted = self._response_is_accepted(fixture, response)
            provider_usage = self._provider_reported_usage
            actual_input_tokens = (
                int(provider_usage["input_tokens"])
                if provider_usage is not None else 0
            )
            actual_output_tokens = (
                int(provider_usage["output_tokens"])
                if provider_usage is not None else 0
            )
            if (
                self._case_http_posts != 1
                or self._case_network_requests != 1
                or self._raw_response is None
                or not self._response_complete
                or self._status_code is None
                or not 200 <= self._status_code < 300
                or response.input_tokens <= 0
                or response.output_tokens <= 0
                or not response.finish_reason
                or not content_accepted
                or provider_usage is None
                or response.input_tokens != actual_input_tokens
                or response.output_tokens != actual_output_tokens
                or actual_input_tokens
                < fixture.definition.estimated_input_tokens
            ):
                self._input_tokens_by_case[fixture.case.case_sha256] = max(
                    0, actual_input_tokens,
                )
                self._output_tokens_by_case[fixture.case.case_sha256] = max(
                    0, actual_output_tokens,
                )
                return DispatchResult(
                    ProbeResultKind.FAILED,
                    (
                        "probe.provider.input_workload_bound_unproven"
                        if provider_usage is not None
                        and actual_input_tokens
                        < fixture.definition.estimated_input_tokens
                        else "probe.provider.incomplete_terminal_evidence"
                    ),
                    self._raw_response or b"", max(0, actual_output_tokens),
                    (
                        max(0, actual_input_tokens)
                        if provider_usage is not None else None
                    ),
                )
            self._input_tokens_by_case[
                fixture.case.case_sha256
            ] = actual_input_tokens
            self._output_tokens_by_case[
                fixture.case.case_sha256
            ] = actual_output_tokens
            return DispatchResult(
                ProbeResultKind.PASS, "probe.provider.accepted",
                self._raw_response, actual_output_tokens, actual_input_tokens,
            )
        except CampaignFixtureError:
            raise
        except Exception:
            raw = self._raw_response or b""
            kind = (
                ProbeResultKind.FAILED
                if self._case_network_requests == 0 or self._response_complete
                else ProbeResultKind.AMBIGUOUS
            )
            code = (
                "probe.provider.terminal_failure"
                if kind is ProbeResultKind.FAILED
                else "probe.provider.ambiguous_transport"
            )
            return DispatchResult(kind, code, raw, None, None)
        finally:
            self._active = None


def _seal_successful_real_records(
    fixtures: Sequence[SyntheticProbeFixture], state: Mapping[str, Any],
    input_tokens_by_case: Mapping[str, int],
    output_tokens_by_case: Mapping[str, int],
    *, authorization_sha256: str, final_execution_head: str,
    key_id: str, signing_key: bytes,
) -> tuple[tuple[bytes, ...], tuple[VerifiedWorkloadEvidenceV1, ...]]:
    packages: list[bytes] = []
    verified: list[VerifiedWorkloadEvidenceV1] = []
    for fixture, record in zip(fixtures, state["records"], strict=True):
        if record["state"] != "PASS_CONSUMED":
            break
        raw = base64.b64decode(record["raw_response_base64"], validate=True)
        actual_input = int(input_tokens_by_case.get(fixture.case.case_sha256, 0))
        actual_output = int(output_tokens_by_case.get(fixture.case.case_sha256, 0))
        if actual_input <= 0 or actual_output <= 0:
            _fail("REAL_RESPONSE_USAGE_NOT_SEALABLE")
        expected = ExpectedWorkloadEvidenceV1(
            authorization_sha256=authorization_sha256,
            final_execution_head=final_execution_head,
            provider=fixture.route.provider, operator=fixture.route.operator,
            destination=fixture.route.destination, protocol=fixture.route.protocol,
            model=fixture.route.model,
            route_fingerprint_sha256=fixture.route.route_fingerprint,
            case_id=fixture.case.case_id, fixture_sha256=fixture.fixture_sha256,
            request_family_sha256=fixture.request_family_sha256,
            request_sha256=fixture.request_sha256,
            input_tokens=fixture.definition.estimated_input_tokens,
            requested_output_tokens=fixture.definition.wire_requested_output_cap,
            key_id=key_id,
        )
        payload = {
            "authorization_sha256": authorization_sha256,
            "case": {"case_id": fixture.case.case_id,
                     "fixture_sha256": fixture.fixture_sha256},
            "final_execution_head": final_execution_head,
            "nonce": {"dispatch_attempt_count": 1,
                      "nonce_sha256": record["nonce_sha256"], "state": "CONSUMED"},
            "request": {"input_tokens": fixture.definition.estimated_input_tokens,
                        "request_family_sha256": fixture.request_family_sha256,
                        "request_sha256": fixture.request_sha256,
                        "requested_output_tokens": fixture.definition.wire_requested_output_cap},
            "result": {"actual_input_tokens": actual_input,
                       "actual_output_tokens": actual_output, "complete": True,
                       "input_accepted": True, "output_accepted": True,
                       "response_sha256": hashlib.sha256(raw).hexdigest(),
                       "terminal_status": "SUCCESS"},
            "route": {"destination": fixture.route.destination,
                      "model": fixture.route.model, "operator": fixture.route.operator,
                      "protocol": fixture.route.protocol, "provider": fixture.route.provider,
                      "route_fingerprint_sha256": fixture.route.route_fingerprint},
        }
        package = seal_external_workload_evidence_v1(
            payload, key_id=key_id, signing_key=signing_key,
        )
        packages.append(package)
        verified.append(validate_external_workload_evidence_v1(
            package, expected=expected, verification_keys={key_id: signing_key},
        ))
    return tuple(packages), tuple(verified)


def _run_guarded_campaign_with_registry_v1(
    fixtures: Sequence[SyntheticProbeFixture], *, registry: ProviderRegistry,
    authorization_sha256: str, final_execution_head: str,
    key_id: str, signing_key: bytes,
    persist: Callable[[Mapping[str, object]], None] | None = None,
    absolute_deadline_unix_seconds: float | None = None,
    wall_clock: Callable[[], float] | None = None,
) -> GuardedRealCampaignResult:
    """Exercise an already-constructed registry under the closed probe plan.

    This private helper never constructs a keyring-backed registry.  The sole
    keyring construction lives inside the fully validated outer orchestrator,
    so there is no importable/recomputable capability token that can unlock a
    second paid entrypoint.
    """
    if (
        not isinstance(authorization_sha256, str)
        or len(authorization_sha256) != 64
        or any(char not in "0123456789abcdef" for char in authorization_sha256)
        or not isinstance(final_execution_head, str)
        or len(final_execution_head) != 40
        or any(char not in "0123456789abcdef" for char in final_execution_head)
        or not key_id
        or not isinstance(signing_key, bytes)
        or len(signing_key) < 32
    ):
        _fail("REAL_CAMPAIGN_AUTHORIZATION_OR_SEAL_INVALID")

    if registry.transport_policy != SingleDispatchTransportPolicyV1.phase_b():
        _fail("SINGLE_DISPATCH_TRANSPORT_POLICY_REQUIRED")
    deadline_clock = wall_clock or time.time
    deadline_holder: dict[str, FullShortProbeCampaign] = {}

    def require_deadline() -> None:
        campaign = deadline_holder.get("campaign")
        if campaign is None:
            _fail("REAL_CAMPAIGN_DEADLINE_GUARD_NOT_ARMED")
        campaign.require_absolute_deadline()

    observer = GuardedProviderDispatch(
        fixtures, registry, deadline_guard=require_deadline,
    )
    for fixture in fixtures:
        if _bind_public_route(registry, fixture.definition) != fixture.route:
            _fail("CURRENT_REGISTRY_ROUTE_BINDING_MISMATCH")
    source_ordinals = tuple(sorted(
        ordinal for fixture in fixtures
        for ordinal in fixture.definition.blocked_shape_ordinals
    ))
    plan = build_probe_campaign_plan(
        (fixture.case for fixture in fixtures), CampaignLimits(),
        source_blocked_shape_ordinals=source_ordinals,
    )
    campaign = FullShortProbeCampaign(
        plan, integrity_key=signing_key, persist=persist,
        absolute_deadline_unix_seconds=absolute_deadline_unix_seconds,
        wall_clock=deadline_clock,
    )
    deadline_holder["campaign"] = campaign
    state = campaign.run(observer)
    packages, verified = _seal_successful_real_records(
        fixtures, state, observer.input_tokens_by_case,
        observer.output_tokens_by_case,
        authorization_sha256=authorization_sha256,
        final_execution_head=final_execution_head, key_id=key_id,
        signing_key=signing_key,
    )
    raw = tuple(
        base64.b64decode(record["raw_response_base64"], validate=True)
        for record in state["records"] if record["raw_response_base64"] is not None
    )
    return GuardedRealCampaignResult(
        campaign_state=MappingProxyType(state), raw_responses=raw,
        sealed_evidence=packages, verified_evidence=verified,
        promoted_evidence=deterministic_promotion_mapping_v1(verified),
        transport_counters=observer.transport_counters,
        privacy_counts=MappingProxyType({
            "RAW_NOVEL_CONTENT_EGRESS_COUNT": 0,
            "REAL_PROJECT_CONTENT_EGRESS_COUNT": 0,
        }),
    )


__all__ = [
    "AUTHORITATIVE_MATRIX_PATH", "AUTHORITATIVE_MATRIX_SHA256",
    "AUTHORITATIVE_SHAPE_COUNT", "BLOCKED_SHAPE_COUNT",
    "BoundPublicRoute", "CampaignFixtureError", "EXACT_PROBE_INPUT_TOKENS",
    "GuardedProviderDispatch", "GuardedRealCampaignResult",
    "OfflineFakeCampaignResult", "ProbeFamilyDefinition", "RELAY_OPERATOR",
    "SyntheticProbeFixture", "build_synthetic_probe_fixtures",
    "derive_probe_families", "load_authoritative_matrix",
    "run_offline_fake_campaign",
]
