import hashlib

import httpx
import pytest

from novel_flywheel.db import Database
from novel_flywheel.domain.models import ModelResponse
from novel_flywheel.models import (
    ModelDispatchScopeViolationError,
    ModelGateway,
    ReviewContractRequalificationScope,
    StructuredRouteQuarantinedError,
)
from novel_flywheel.providers.registry import ResolvedModel
from novel_flywheel.providers.http import HttpProvider
from novel_flywheel.structured_artifacts import StructuredArtifactContract
from tools.canary.review_requalification_resume import canonical_candidate_sha256


class _Adapter:
    def __init__(self, *, failure: Exception | None = None) -> None:
        self.failure = failure
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        if self.failure is not None:
            raise self.failure
        return ModelResponse(
            text='{"verdict":"REJECT"}',
            input_tokens=10,
            output_tokens=12,
            finish_reason="stop",
        )


class _Registry:
    def __init__(self, adapter: _Adapter) -> None:
        self.adapter = adapter

    def resolve(self, provider_id, model_id, **_kwargs):
        return ResolvedModel(
            provider_id,
            model_id,
            "current-review-model",
            self.adapter,
            {"structured_output": "strict_json_schema"},
            "a" * 64,
        )


class _PhysicalAttemptAdapter(HttpProvider):
    async def complete(self, _request):
        await self.post_stream(
            "chat/completions",
            payload={"stream": True, "stream_options": {"include_usage": True}},
            headers={},
        )


class _PhysicalAttemptRegistry:
    def __init__(self, handler) -> None:
        self.handler = handler
        self.adapter = None
        self.transport_policies = []

    def resolve(
        self, provider_id, model_id, *, role=None, lane=None,
        transport_policy=None,
    ):
        self.transport_policies.append(transport_policy)
        self.adapter = _PhysicalAttemptAdapter(
            "https://provider.invalid/v1",
            "secret",
            transport_policy=transport_policy,
            injected_http_transport=httpx.MockTransport(self.handler),
        )
        return ResolvedModel(
            provider_id,
            model_id,
            "current-review-model",
            self.adapter,
            {"structured_output": "strict_json_schema"},
            "a" * 64,
        )


def _contract(name: str = "draft_atomic_semantic_receipt", version: int = 1):
    return StructuredArtifactContract(
        name=name,
        version=version,
        schema={
            "type": "object",
            "properties": {"verdict": {"type": "string"}},
            "required": ["verdict"],
            "additionalProperties": False,
        },
        runtime_authority={"candidate": "b" * 64},
    )


def _setup(tmp_path, adapter: _Adapter):
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_project("project-1", "Story", "short", tmp_path / "story")
    db.create_run("run-1", "project-1", "short-story", status="failed")
    db.save_role_binding("review", "provider-1", "model-1", None, None)
    gateway = ModelGateway(db, _Registry(adapter))
    contract = _contract()
    db.save_structured_route_outcome(
        provider_id="provider-1",
        model_id="model-1",
        route_fingerprint="a" * 64,
        execution_mode="strict_json_schema",
        contract_name=contract.name,
        schema_sha256=contract.schema_sha256(),
        outcome="protocol_invalid",
        failure_reason="native_protocol_rejected",
    )
    db.save_structured_route_outcome(
        provider_id="provider-1",
        model_id="model-1",
        route_fingerprint="a" * 64,
        execution_mode="plain",
        contract_name=contract.name,
        schema_sha256=contract.schema_sha256(),
        outcome="protocol_invalid",
        failure_reason="native_protocol_rejected",
    )
    db.save_structured_route_outcome(
        provider_id="provider-1",
        model_id="model-1",
        route_fingerprint="a" * 64,
        execution_mode="plain",
        contract_name=contract.name,
        schema_sha256=contract.schema_sha256(),
        outcome="protocol_invalid",
        failure_reason="native_protocol_rejected",
    )
    return db, gateway, contract


def _scope(contract: StructuredArtifactContract, **updates):
    values = {
        "run_id": "run-1",
        "candidate_sha256": "b" * 64,
        "role": "review",
        "stage": "review",
        "contract_name": contract.name,
        "contract_version": contract.version,
        "schema_sha256": contract.schema_sha256(),
        "reasoning_policy": "current_provider_default",
        "stage_role": "NORMAL",
        "allowed_routes": (("provider-1", "model-1", "a" * 64),),
        "authorization_sha256": hashlib.sha256(b"authorization").hexdigest(),
        "max_dispatches": 4,
        "max_dispatches_per_route": 2,
    }
    values.update(updates)
    return ReviewContractRequalificationScope(**values)


def test_resume_cli_uses_workflow_text_hash_across_crlf_storage(tmp_path):
    candidate = tmp_path / "candidate.md"
    candidate.write_bytes("潮汐\r\n证词".encode("utf-8"))
    expected = hashlib.sha256("潮汐\n证词".encode("utf-8")).hexdigest()
    assert canonical_candidate_sha256(candidate) == expected


@pytest.mark.asyncio
async def test_quarantine_requires_exact_bound_requalification_scope(tmp_path):
    adapter = _Adapter()
    _db, gateway, contract = _setup(tmp_path, adapter)

    with pytest.raises(StructuredRouteQuarantinedError):
        await gateway.complete_route(
            "primary", "review", "system", "user",
            contract=contract, stage="review",
        )
    assert adapter.requests == []

    with gateway.bind_review_contract_requalification(
        _scope(contract), candidate_sha256="b" * 64,
    ):
        await gateway.complete_route(
            "primary", "review", "system", "user",
            contract=contract, stage="review",
        )
    assert len(adapter.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scope_update",
    [
        {"candidate_sha256": "c" * 64},
        {"contract_name": "draft_segment_semantic_receipt"},
        {"contract_version": 99},
        {"schema_sha256": "d" * 64},
        {"reasoning_policy": "disabled"},
        {"stage_role": "RECOVERY"},
        {"allowed_routes": (("other", "model-1", "a" * 64),)},
    ],
)
async def test_wrong_requalification_identity_is_rejected_before_adapter(
    tmp_path, scope_update,
):
    adapter = _Adapter()
    _db, gateway, contract = _setup(tmp_path, adapter)
    with pytest.raises(ModelDispatchScopeViolationError):
        with gateway.bind_review_contract_requalification(
            _scope(contract, **scope_update), candidate_sha256="b" * 64,
        ):
            await gateway.complete_route(
                "primary", "review", "system", "user",
                contract=contract, stage="review",
            )
    assert adapter.requests == []


@pytest.mark.asyncio
async def test_requalification_failure_stays_quarantined_and_is_durable(tmp_path):
    adapter = _Adapter(failure=RuntimeError("deterministic protocol failure"))
    db, gateway, contract = _setup(tmp_path, adapter)
    scope = _scope(contract)
    with gateway.bind_review_contract_requalification(
        scope, candidate_sha256="b" * 64,
    ):
        with pytest.raises(RuntimeError):
            await gateway.complete_route(
                "primary", "review", "system", "user",
                contract=contract, stage="review",
            )

    fresh_gateway = ModelGateway(db, _Registry(adapter))
    with fresh_gateway.bind_review_contract_requalification(
        scope, candidate_sha256="b" * 64,
    ):
        with pytest.raises(ModelDispatchScopeViolationError):
            await fresh_gateway.complete_route(
                "primary", "review", "system", "user",
                contract=contract, stage="review",
            )
    qualification = db.get_structured_route_qualification(
        provider_id="provider-1", model_id="model-1",
        route_fingerprint="a" * 64,
        execution_mode="strict_json_schema",
        contract_name=contract.name,
        schema_sha256=contract.schema_sha256(),
    )
    assert qualification["status"] == "quarantined"
    assert len(adapter.requests) == 1


@pytest.mark.asyncio
async def test_only_transient_same_condition_failure_allows_second_route_attempt(
    tmp_path,
):
    adapter = _Adapter(failure=httpx.ConnectError("temporary disconnect"))
    db, gateway, contract = _setup(tmp_path, adapter)
    scope = _scope(contract)
    with gateway.bind_review_contract_requalification(
        scope, candidate_sha256="b" * 64,
    ):
        with pytest.raises(httpx.ConnectError):
            await gateway.complete_route(
                "primary", "review", "system", "user",
                contract=contract, stage="review",
            )

    with gateway.bind_review_contract_requalification(
        scope, candidate_sha256="b" * 64,
    ):
        with pytest.raises(httpx.ConnectError):
            await gateway.complete_route(
                "primary", "review", "system", "user",
                contract=contract, stage="review",
            )

    fresh_gateway = ModelGateway(db, _Registry(adapter))
    with fresh_gateway.bind_review_contract_requalification(
        scope, candidate_sha256="b" * 64,
    ):
        with pytest.raises(ModelDispatchScopeViolationError):
            await fresh_gateway.complete_route(
                "primary", "review", "system", "user",
                contract=contract, stage="review",
            )
    assert len(adapter.requests) == 2


@pytest.mark.asyncio
async def test_requalification_claim_allows_only_one_physical_http_attempt(
    tmp_path,
):
    physical_requests = []

    def handler(request):
        physical_requests.append(request)
        return httpx.Response(
            400,
            request=request,
            json={"error": "stream_options unsupported"},
        )

    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_project("project-1", "Story", "short", tmp_path / "story")
    db.create_run("run-1", "project-1", "short-story", status="failed")
    db.save_role_binding("review", "provider-1", "model-1", None, None)
    registry = _PhysicalAttemptRegistry(handler)
    gateway = ModelGateway(db, registry)
    contract = _contract()
    db.save_structured_route_outcome(
        provider_id="provider-1",
        model_id="model-1",
        route_fingerprint="a" * 64,
        execution_mode="strict_json_schema",
        contract_name=contract.name,
        schema_sha256=contract.schema_sha256(),
        outcome="protocol_invalid",
        failure_reason="native_protocol_rejected",
    )

    with gateway.bind_review_contract_requalification(
        _scope(contract), candidate_sha256="b" * 64,
    ):
        with pytest.raises(httpx.HTTPStatusError):
            await gateway.complete_route(
                "primary", "review", "system", "user",
                contract=contract, stage="review",
            )

    assert len(physical_requests) == 1
    assert registry.transport_policies[0].max_http_post_attempts == 1
    assert registry.adapter.transport_attempt_snapshot() == {
        "guard_active": True,
        "max_http_post_attempts": 1,
        "model_logical_calls": 1,
        "real_provider_request_attempts": 1,
        "http_post_attempts": 1,
        "network_request_attempts": 1,
        "sdk_retries_disabled": True,
        "transport_request_retries_disabled": True,
        "application_second_dispatch_allowed": False,
    }
    claims = [
        item for item in db.list_workflow_attempts("run-1")
        if item["action"] == "review_contract_requalification_dispatch"
    ]
    assert len(claims) == 1


def test_durable_total_requalification_cap_cannot_reset(tmp_path):
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_project("project-1", "Story", "short", tmp_path / "story")
    db.create_run("run-1", "project-1", "short-story", status="failed")
    authorization = "a" * 64
    for index in range(4):
        db.claim_review_requalification_dispatch(
            run_id="run-1",
            authorization_sha256=authorization,
            route_identity_sha256=hashlib.sha256(
                f"route-{index // 2}".encode()
            ).hexdigest(),
            request_condition_sha256=hashlib.sha256(
                f"request-{index}".encode()
            ).hexdigest(),
            max_dispatches=4,
            max_dispatches_per_route=2,
        )
    with pytest.raises(ValueError, match="limit exhausted"):
        db.claim_review_requalification_dispatch(
            run_id="run-1",
            authorization_sha256=authorization,
            route_identity_sha256="f" * 64,
            request_condition_sha256="e" * 64,
            max_dispatches=4,
            max_dispatches_per_route=2,
        )


@pytest.mark.asyncio
async def test_valid_outcome_qualifies_only_exact_scope_and_closes_authorization(
    tmp_path,
):
    adapter = _Adapter()
    db, gateway, contract = _setup(tmp_path, adapter)
    scope = _scope(contract)
    with gateway.bind_review_contract_requalification(
        scope, candidate_sha256="b" * 64,
    ):
        result = await gateway.complete_route(
            "primary", "review", "system", "user",
            contract=contract, stage="review",
        )
        gateway.record_structured_contract_outcome(
            result.receipt, contract, outcome="valid",
        )

    exact = db.get_structured_route_qualification(
        provider_id="provider-1", model_id="model-1",
        route_fingerprint="a" * 64,
        execution_mode="strict_json_schema",
        contract_name=contract.name,
        schema_sha256=contract.schema_sha256(),
    )
    assert exact["status"] == "qualified"
    claims = [
        item for item in db.list_workflow_attempts("run-1")
        if item["action"] == "review_contract_requalification_dispatch"
    ]
    assert len(claims) == 1
    assert claims[0]["state"] == "qualified"
    assert db.get_structured_route_qualification(
        provider_id="provider-1", model_id="model-1",
        route_fingerprint="a" * 64,
        execution_mode="strict_json_schema",
        contract_name="other_contract",
        schema_sha256=contract.schema_sha256(),
    ) is None
