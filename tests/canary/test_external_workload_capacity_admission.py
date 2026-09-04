from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

import novel_flywheel.full_short_execution as full_short_execution
import novel_flywheel.workflows as workflows
from novel_flywheel.external_workload_evidence import (
    ExpectedWorkloadEvidenceV1,
    seal_external_workload_evidence_v1,
    validate_external_workload_evidence_v1,
)
from novel_flywheel.providers.registry import ProviderRegistry
from novel_flywheel.route_capabilities import (
    CapabilityStatus,
    RouteCapabilityRecordV1,
    RouteCapabilityRegistryV1,
)
from novel_flywheel.stage_capacity import (
    CapacityAdmissionFailureV1,
    _issue_verified_external_workload_capacity_issuer_v1,
)
from novel_flywheel.runtime_fingerprint_build import domain_sha256
from tests.canary.test_full_short_runner_hardening import (
    _bound_project,
    _logical_plan,
)
from tests.test_full_short_execution import (
    _authorize_offline,
    _bind_route_with_capacity,
    _egress,
    _policy,
    _store,
)
from novel_flywheel.full_short_execution import (
    FullShortDispatchLedgerObserverV1,
    full_short_workload_request_family_id_v1,
    full_short_workload_partition_sha256_v1,
)
from novel_flywheel.full_short_probe_campaign import ProbeCase, ProbeRouteIdentity
from tools.canary import first_trustworthy_full_short_runner as runner


KEY = b"external-workload-capacity-test-key-32-bytes"
AUTHORIZATION_SHA256 = "a" * 64
HEAD = "b" * 40


def _verified_evidence(
    *, repo, db, plan_entry, head=HEAD, provider_name="Provider",
    request_family_sha256=None, request_sha256="9" * 64,
    input_tokens=30_000, requested_output_tokens=1024,
):
    provider = db.get_provider("provider")
    model = db.get_model("model")
    assert provider is not None and model is not None
    destination = runner._destination(provider)
    route_fingerprint = ProviderRegistry.route_fingerprint(provider, model)
    family_sha256 = runner.full_short_workload_request_family_sha256_v1(
        plan_entry,
        provider="Provider",
        operator="THIRD_PARTY_RELAY_UNVERIFIED_UPSTREAM",
        destination=destination,
        protocol="anthropic",
        model="model",
        route_fingerprint_sha256=route_fingerprint,
    )
    expected = ExpectedWorkloadEvidenceV1(
        authorization_sha256=AUTHORIZATION_SHA256,
        final_execution_head=head,
        provider=provider_name,
        operator="THIRD_PARTY_RELAY_UNVERIFIED_UPSTREAM",
        destination=destination,
        protocol="anthropic",
        model="model",
        route_fingerprint_sha256=route_fingerprint,
        case_id="planning-fallback-contract-family",
        fixture_sha256="c" * 64,
        request_family_sha256=request_family_sha256 or family_sha256,
        request_sha256=request_sha256,
        input_tokens=input_tokens,
        requested_output_tokens=requested_output_tokens,
        key_id="campaign-key",
    )
    payload = {
        "authorization_sha256": expected.authorization_sha256,
        "case": {
            "case_id": expected.case_id,
            "fixture_sha256": expected.fixture_sha256,
        },
        "final_execution_head": expected.final_execution_head,
        "nonce": {
            "dispatch_attempt_count": 1,
            "nonce_sha256": "d" * 64,
            "state": "CONSUMED",
        },
        "request": {
            "input_tokens": expected.input_tokens,
            "request_family_sha256": expected.request_family_sha256,
            "request_sha256": expected.request_sha256,
            "requested_output_tokens": expected.requested_output_tokens,
        },
        "result": {
            "actual_input_tokens": expected.input_tokens,
            "actual_output_tokens": min(64, requested_output_tokens),
            "complete": True,
            "input_accepted": True,
            "output_accepted": True,
            "response_sha256": "e" * 64,
            "terminal_status": "SUCCESS",
        },
        "route": {
            "destination": expected.destination,
            "model": expected.model,
            "operator": expected.operator,
            "protocol": expected.protocol,
            "provider": expected.provider,
            "route_fingerprint_sha256": expected.route_fingerprint_sha256,
        },
    }
    package = seal_external_workload_evidence_v1(
        payload, key_id="campaign-key", signing_key=KEY,
    )
    return validate_external_workload_evidence_v1(
        package, expected=expected, verification_keys={"campaign-key": KEY},
    )


def _authorized_case(evidence, *, ordinal=1, blocked_shape_ordinals=(1,)):
    route = ProbeRouteIdentity(
        provider=evidence.provider,
        operator=evidence.operator,
        destination_sha256=hashlib.sha256(
            evidence.destination.encode("utf-8")
        ).hexdigest(),
        protocol=evidence.protocol,
        model=evidence.model,
        route_fingerprint=evidence.route_fingerprint_sha256,
    )
    case = ProbeCase(
        ordinal=ordinal,
        case_id=evidence.case_id,
        route=route,
        fixture_sha256=evidence.fixture_sha256,
        input_envelope_sha256=evidence.request_sha256,
        estimated_input_tokens=evidence.input_tokens,
        wire_requested_output_cap=evidence.requested_output_tokens,
        blocked_shape_ordinals=blocked_shape_ordinals,
    )
    return {
        "ordinal": ordinal,
        "case_id": evidence.case_id,
        "case_sha256": case.case_sha256,
        "route": {
            "provider": evidence.provider,
            "operator": evidence.operator,
            "destination": evidence.destination,
            "destination_sha256": route.destination_sha256,
            "protocol": evidence.protocol,
            "model": evidence.model,
            "route_fingerprint": evidence.route_fingerprint_sha256,
        },
        "fixture_sha256": evidence.fixture_sha256,
        "input_envelope_sha256": evidence.request_sha256,
        "request_family_sha256": evidence.request_family_sha256,
        "request_sha256": evidence.request_sha256,
        "estimated_input_tokens": evidence.input_tokens,
        "wire_requested_output_cap": evidence.requested_output_tokens,
        "blocked_shape_ordinals": list(blocked_shape_ordinals),
    }


def _unknown_route_setup(tmp_path, monkeypatch):
    repo, data, project_id, db = _bound_project(tmp_path)
    path = repo / runner._ROUTE_CAPABILITY_REGISTRY_PATH_V1
    registry = RouteCapabilityRegistryV1.from_document(
        json.loads(path.read_text(encoding="utf-8"))
    )
    records = []
    for record in registry.records:
        if (record.role, record.lane) != ("planning", "primary"):
            records.append(record)
            continue
        records.append(RouteCapabilityRecordV1.create(
            role=record.role, lane=record.lane, provider=record.provider,
            provider_id_sha256=record.provider_id_sha256,
            operator=record.operator, destination=record.destination,
            protocol=record.protocol, model=record.model,
            model_id_sha256=record.model_id_sha256,
            route_fingerprint=record.route_fingerprint,
            context_window_tokens=None, max_output_tokens=None,
            reasoning_token_accounting=record.reasoning_token_accounting,
            reasoning_output_reservation=record.reasoning_output_reservation,
            reasoning_token_reserve=record.reasoning_token_reserve,
            capability_status=CapabilityStatus.UNKNOWN_BLOCKED,
            blocking_reason_codes=("NO_TRUSTWORTHY_EVIDENCE",),
        ))
    path.write_text(
        json.dumps(RouteCapabilityRegistryV1.create(records).to_document()),
        encoding="utf-8",
    )
    plan = _logical_plan()
    plan[0].update({
        "stage_id": "planning-adaptation-segment-rebuild-03-attempt-1",
        "logical_stage_base_id": (
            "planning-adaptation-segment-rebuild-03-attempt-1"
        ),
        "logical_stage_id": (
            "planning-adaptation-segment-rebuild-03-attempt-1"
        ),
        "contract_name": "planning_event_realizations",
        "contract_schema_sha256": hashlib.sha256(
            b"planning_event_realizations"
        ).hexdigest(),
        "contract_runtime_input_required": True,
    })
    monkeypatch.setenv("NOVEL_SHORT_CANONICAL_V2", "1")
    monkeypatch.setattr(runner, "_git", lambda _repo, *args: (
        HEAD if args == ("rev-parse", "HEAD")
        else "master" if args == ("branch", "--show-current")
        else ""
    ))
    return repo, data, project_id, db, plan


def _source_shape_as_logical_entry(shape, ordinal):
    stage_id = str(shape["stage"])
    role = str(shape["role"])
    structured_contracts = {
        "planning-adaptation-segment-": "planning_event_realizations",
        "planning-causal-chain-packet-": "short_causal_chain",
        "planning-execution-segment-": "execution_manifest",
        "final_review-window-": "final_review_window",
    }
    contract_name = None
    for prefix, candidate in structured_contracts.items():
        if stage_id.startswith(prefix):
            contract_name = candidate
            break
    if stage_id == "final_review-adjudication":
        contract_name = "full_short_final_review"
    structured = contract_name is not None
    if contract_name is None:
        # Source maintenance contracts contain window-derived dynamic labels.
        contract_name = f"plain-text-{stage_id}"
    return {
        "ordinal": ordinal,
        "stage_id": stage_id,
        "logical_stage_base_id": stage_id,
        "logical_stage_id": stage_id,
        "role": role,
        "route_lane": str(shape["route"]),
        "contract_name": contract_name,
        "contract_version": 1,
        "contract_schema_sha256": hashlib.sha256(
            contract_name.encode("utf-8")
        ).hexdigest(),
        "contract_runtime_input_required": structured,
        "requested_output_tokens": int(
            shape["provider_wire_requested_output_cap"]
        ),
    }


def test_authoritative_blocked_shapes_collapse_to_exact_eight_families():
    matrix_path = Path(
        "docs/superpowers/reports/"
        "full-short-capacity-final-one-round-confirmation-v1/"
        "exact-ready-authoritative-physical-attempt-matrix-v1.json"
    )
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    blocked = [
        item for item in matrix["attempts"]
        if item["admission_result"] == "BLOCKED"
    ]
    assert len(blocked) == 111
    hashes = set()
    family_ids = set()
    for ordinal, shape in enumerate(blocked, 1):
        entry = _source_shape_as_logical_entry(shape, ordinal)
        family_ids.add(full_short_workload_request_family_id_v1(entry))
        hashes.add(full_short_execution.full_short_workload_request_family_sha256_v1(
            entry,
            provider=str(shape["provider_id_sha256"]),
            operator=str(shape["provider_operator"]),
            destination=str(shape["destination_sha256"]),
            protocol=str(shape["protocol"]),
            model=str(shape["model"]),
            route_fingerprint_sha256=str(shape["route_fingerprint"]),
        ))
    assert family_ids == {
        "draft_plain", "polish_plain", "planning_adaptation",
        "causal_chain", "execution_manifest", "final_review_window",
        "final_review_adjudication", "maintenance_plain",
    }
    assert len(hashes) == 8


def test_dynamic_plain_contract_names_and_stage_ids_do_not_split_family():
    first = _source_shape_as_logical_entry({
        "stage": "maintenance-map-001-mw-aaaa-window",
        "role": "maintenance", "route": "primary",
        "provider_wire_requested_output_cap": 800,
    }, 1)
    second = dict(first)
    second.update({
        "ordinal": 99,
        "stage_id": "maintenance-map-099-mw-bbbb-mw-cccc-window",
        "logical_stage_base_id": "maintenance-map-099-mw-bbbb-mw-cccc-window",
        "logical_stage_id": "maintenance-map-099-mw-bbbb-mw-cccc-window",
        "contract_name": "different-dynamic-maintenance-contract",
        "contract_schema_sha256": "f" * 64,
        "requested_output_tokens": 2048,
    })
    route = dict(
        provider="Provider", operator="Operator",
        destination="https://unit.test/v1", protocol="anthropic",
        model="model", route_fingerprint_sha256="a" * 64,
    )
    assert (
        full_short_execution.full_short_workload_request_family_sha256_v1(
            first, **route,
        )
        == full_short_execution.full_short_workload_request_family_sha256_v1(
            second, **route,
        )
    )


def test_logical_family_hash_delegates_to_shared_probe_partition_hash():
    entry = _source_shape_as_logical_entry({
        "stage": "planning-causal-chain-packet-abcd",
        "role": "planning", "route": "primary",
        "provider_wire_requested_output_cap": 1200,
    }, 1)
    route = dict(
        provider="Provider", operator="Operator",
        destination="https://unit.test/v1", protocol="anthropic",
        model="model", route_fingerprint_sha256="a" * 64,
    )
    assert full_short_execution.full_short_workload_request_family_sha256_v1(
        entry, **route,
    ) == full_short_workload_partition_sha256_v1(
        family_id="causal_chain",
        contract_name="short_causal_chain",
        contract_version=1,
        contract_schema_sha256=entry["contract_schema_sha256"],
        **route,
    )


def test_unknown_or_structurally_wrong_workload_family_fails_closed():
    entry = _source_shape_as_logical_entry({
        "stage": "maintenance-map-001-window", "role": "maintenance",
        "route": "primary", "provider_wire_requested_output_cap": 800,
    }, 1)
    entry["contract_runtime_input_required"] = True
    with pytest.raises(
        full_short_execution.FullShortExecutionBoundaryError,
        match="WORKLOAD_REQUEST_FAMILY_UNKNOWN",
    ):
        full_short_workload_request_family_id_v1(entry)


def test_unknown_tracked_route_is_eligible_only_with_complete_verified_family(
    tmp_path, monkeypatch,
) -> None:
    repo, data, project_id, db, plan = _unknown_route_setup(
        tmp_path, monkeypatch,
    )
    evidence = _verified_evidence(
        repo=repo, db=db, plan_entry=plan[0],
    )

    _actual, public = runner.collect_live_bindings(
        repo=repo, data_dir=data, project_id=project_id, run_id="external",
        logical_stage_plan=plan, store_root=tmp_path / "control-store",
        verified_external_workload_evidence=(evidence,),
        external_workload_authorized_cases=(_authorized_case(evidence),),
        external_workload_authorization_sha256=AUTHORIZATION_SHA256,
        external_workload_verification_keys={"campaign-key": KEY},
    )

    selected = next(
        item for item in public["routes"]
        if item["role"] == "planning" and item["lane"] == "primary"
    )
    assert public["authorization_eligible"] is True
    assert selected["route_context_capability_source"] == (
        "verified_external_workload_evidence"
    )
    assert selected["route_context_capability_limit_tokens"] == 31_024
    assert selected["max_output_tokens"] == 1024
    assert selected["external_workload_evidence_families"][0][
        "evidence_sha256"
    ] == evidence.evidence_sha256
    assert selected["external_workload_evidence_families"][0][
        "request_sha256"
    ] == evidence.request_sha256


def test_outer_authorization_projection_preserves_unknown_route_source_truth(
    tmp_path, monkeypatch,
) -> None:
    repo, data, project_id, _db, plan = _unknown_route_setup(
        tmp_path, monkeypatch,
    )

    actual, public = runner.collect_live_bindings(
        repo=repo,
        data_dir=data,
        project_id=project_id,
        run_id="outer-projection",
        logical_stage_plan=plan,
        store_root=tmp_path / "control-store",
        outer_authorization_projection=True,
    )

    selected = next(
        item for item in public["routes"]
        if item["role"] == "planning" and item["lane"] == "primary"
    )
    assert actual["head"] == HEAD
    assert public["authorization_eligible"] is False
    assert selected["route_context_capability_limit_tokens"] is None
    assert selected["route_context_capability_source"] is None
    assert selected["route_capability_status"] == "UNKNOWN_BLOCKED"


def test_outer_authorization_projection_rejects_external_evidence_mix(
    tmp_path, monkeypatch,
) -> None:
    repo, data, project_id, db, plan = _unknown_route_setup(
        tmp_path, monkeypatch,
    )
    evidence = _verified_evidence(repo=repo, db=db, plan_entry=plan[0])
    with pytest.raises(CapacityAdmissionFailureV1):
        runner.collect_live_bindings(
            repo=repo,
            data_dir=data,
            project_id=project_id,
            run_id="outer-projection-mixed",
            logical_stage_plan=plan,
            store_root=tmp_path / "control-store",
            outer_authorization_projection=True,
            verified_external_workload_evidence=(evidence,),
            external_workload_authorized_cases=(_authorized_case(evidence),),
            external_workload_authorization_sha256=AUTHORIZATION_SHA256,
            external_workload_verification_keys={"campaign-key": KEY},
        )


@pytest.mark.parametrize("mismatch", ["head", "route", "request", "output"])
def test_wrong_head_route_request_or_output_remains_blocked(
    tmp_path, monkeypatch, mismatch,
) -> None:
    repo, data, project_id, db, plan = _unknown_route_setup(
        tmp_path, monkeypatch,
    )
    changes = {}
    if mismatch == "head":
        changes["head"] = "f" * 40
    elif mismatch == "route":
        changes["provider_name"] = "Different Provider"
    elif mismatch == "request":
        changes["request_family_sha256"] = "f" * 64
    else:
        changes["requested_output_tokens"] = 127
    evidence = _verified_evidence(
        repo=repo, db=db, plan_entry=plan[0], **changes,
    )
    authorized_evidence = _verified_evidence(
        repo=repo, db=db, plan_entry=plan[0],
    )

    with pytest.raises(CapacityAdmissionFailureV1):
        runner.collect_live_bindings(
            repo=repo, data_dir=data, project_id=project_id,
            run_id="external-mismatch", logical_stage_plan=plan,
            store_root=tmp_path / "control-store",
            verified_external_workload_evidence=(evidence,),
            external_workload_authorized_cases=(
                _authorized_case(authorized_evidence),
            ),
            external_workload_authorization_sha256=AUTHORIZATION_SHA256,
            external_workload_verification_keys={"campaign-key": KEY},
        )


def test_missing_family_and_arbitrary_json_cannot_promote_unknown_route(
    tmp_path, monkeypatch,
) -> None:
    repo, data, project_id, _db, plan = _unknown_route_setup(
        tmp_path, monkeypatch,
    )
    kwargs = dict(
        repo=repo, data_dir=data, project_id=project_id,
        run_id="external-missing", logical_stage_plan=plan,
        store_root=tmp_path / "control-store",
    )
    with pytest.raises(CapacityAdmissionFailureV1):
        runner.collect_live_bindings(**kwargs)
    with pytest.raises(CapacityAdmissionFailureV1):
        runner.collect_live_bindings(
            **kwargs,
            verified_external_workload_evidence=(json.loads("{}"),),
            external_workload_authorization_sha256=AUTHORIZATION_SHA256,
            external_workload_verification_keys={"campaign-key": KEY},
        )


def test_constructed_or_unreverified_evidence_cannot_promote_unknown_route(
    tmp_path, monkeypatch,
) -> None:
    repo, data, project_id, db, plan = _unknown_route_setup(
        tmp_path, monkeypatch,
    )
    evidence = _verified_evidence(repo=repo, db=db, plan_entry=plan[0])
    kwargs = dict(
        repo=repo, data_dir=data, project_id=project_id,
        run_id="external-reverification", logical_stage_plan=plan,
        store_root=tmp_path / "control-store",
        verified_external_workload_evidence=(evidence,),
        external_workload_authorized_cases=(_authorized_case(evidence),),
        external_workload_authorization_sha256=AUTHORIZATION_SHA256,
    )
    with pytest.raises(CapacityAdmissionFailureV1):
        runner.collect_live_bindings(**kwargs)
    with pytest.raises(CapacityAdmissionFailureV1):
        runner.collect_live_bindings(
            **kwargs,
            external_workload_verification_keys={"campaign-key": b"x" * 32},
        )
    fabricated = replace(evidence, package_bytes=b"{}")
    with pytest.raises(CapacityAdmissionFailureV1):
        runner.collect_live_bindings(
            **{**kwargs, "verified_external_workload_evidence": (fabricated,)},
            external_workload_verification_keys={"campaign-key": KEY},
        )


def test_external_evidence_hash_is_bound_into_capacity_admission_receipt(
    tmp_path, monkeypatch,
) -> None:
    repo, data, project_id, db, plan = _unknown_route_setup(
        tmp_path, monkeypatch,
    )
    monkeypatch.setattr(runner, "_git", lambda _repo, *args: (
        "a" * 40 if args == ("rev-parse", "HEAD")
        else "master" if args == ("branch", "--show-current")
        else ""
    ))
    evidence = _verified_evidence(
        repo=repo, db=db, plan_entry=plan[0], head="a" * 40,
    )
    _actual, public = runner.collect_live_bindings(
        repo=repo, data_dir=data, project_id=project_id,
        run_id="external-receipt", logical_stage_plan=plan,
        store_root=tmp_path / "binding-store",
        verified_external_workload_evidence=(evidence,),
        external_workload_authorized_cases=(_authorized_case(evidence),),
        external_workload_authorization_sha256=AUTHORIZATION_SHA256,
        external_workload_verification_keys={"campaign-key": KEY},
    )
    selected = next(
        item for item in public["routes"]
        if item["role"] == "planning" and item["lane"] == "primary"
    )
    store = _store(tmp_path / "receipt")
    execution_id = "external-evidence-receipt"
    logical_plan = tuple(plan)
    routes = (selected,)
    _authorize_offline(
        store, execution_id, routes=routes,
        logical_stage_plan=logical_plan,
    )
    observer = FullShortDispatchLedgerObserverV1(
        store=store,
        execution_id=execution_id,
        policy=_policy(
            store, routes=routes, logical_stage_plan=logical_plan,
        ),
        authorized_routes=routes,
        egress_policy=_egress(),
        external_workload_capacity_issuer=(
            _issue_verified_external_workload_capacity_issuer_v1(
                evidence_sha256s=(evidence.evidence_sha256,),
            )
        ),
    )
    _bind_route_with_capacity(
        observer, role="planning", lane="primary",
        provider_id="provider", model_id="model",
        route_fingerprint=selected["route_fingerprint"],
        resolve_route=False,
    )
    receipt = store.load_capacity_admission_receipt(
        execution_id=execution_id,
        plan_sha256=str(observer.pending_capacity_plan_sha256),
    )
    assert receipt["external_workload_evidence_sha256"] == (
        evidence.evidence_sha256
    )
    assert receipt["route_capability_snapshot_sha256"] == (
        evidence.evidence_sha256
    )
    forged = dict(receipt)
    forged.pop("capacity_admission_receipt_sha256")
    forged["external_workload_evidence_sha256"] = "f" * 64
    forged["capacity_admission_receipt_sha256"] = domain_sha256(
        "novel-flywheel-capacity-admission-receipt-v1", forged,
    )
    with pytest.raises(
        full_short_execution.FullShortExecutionBoundaryError,
        match="CAPACITY_ADMISSION_EXTERNAL_EVIDENCE_INVALID",
    ):
        full_short_execution._validate_capacity_admission_receipt_v1(
            forged, execution_id=execution_id,
            plan_sha256=str(observer.pending_capacity_plan_sha256),
        )


def test_validated_external_evidence_elevates_production_capacity_path(
    tmp_path, monkeypatch,
) -> None:
    """The production observer must carry opaque proof into build and bind."""

    repo, data, project_id, db, logical_plan = _unknown_route_setup(
        tmp_path, monkeypatch,
    )
    evidence = _verified_evidence(
        repo=repo,
        db=db,
        plan_entry=logical_plan[0],
        input_tokens=33_200,
        requested_output_tokens=232,
    )
    _actual, public = runner.collect_live_bindings(
        repo=repo,
        data_dir=data,
        project_id=project_id,
        run_id="external-production-capacity-path",
        logical_stage_plan=logical_plan,
        store_root=tmp_path / "binding-store",
        verified_external_workload_evidence=(evidence,),
        external_workload_authorized_cases=(_authorized_case(evidence),),
        external_workload_authorization_sha256=AUTHORIZATION_SHA256,
        external_workload_verification_keys={"campaign-key": KEY},
    )
    selected = next(
        item for item in public["routes"]
        if item["role"] == "planning" and item["lane"] == "primary"
    )
    assert selected["route_context_capability_limit_tokens"] == 33_432

    store = _store(tmp_path / "execution")
    execution_id = "external-production-capacity-path"
    routes = (selected,)
    policy = _policy(
        store, routes=routes, logical_stage_plan=tuple(logical_plan),
    )
    policy["execution_head"] = HEAD
    policy.pop("policy_sha256")
    policy["policy_sha256"] = domain_sha256(
        "novel-flywheel-full-short-execution-policy-v1", policy,
    )
    permission = store.create_permission(
        execution_id=execution_id,
        authorization_text_sha256="3" * 64,
        policy=policy,
        external_actions_enabled=False,
    )
    approval = store.create_jit_approval(
        execution_id=execution_id,
        policy=policy,
        permission=permission,
        external_actions_enabled=False,
    )
    store.reserve_nonce(
        execution_id=execution_id,
        policy=policy,
        approval=approval,
        external_actions_enabled=False,
    )
    observer = FullShortDispatchLedgerObserverV1(
        store=store,
        execution_id=execution_id,
        policy=policy,
        authorized_routes=routes,
        egress_policy=_egress(),
        external_workload_capacity_issuer=(
            _issue_verified_external_workload_capacity_issuer_v1(
                evidence_sha256s=(evidence.evidence_sha256,),
            )
        ),
    )
    expected = observer._next_logical_stage_plan_entry()
    context = observer.capacity_admission_context(
        route="primary", role="planning", physical_attempt=1,
    )
    assert context["route_context_capability_limit_tokens"] == 33_432
    assert "external_workload_capacity_capability" in context

    rendered_request_sha256 = hashlib.sha256(b"\n\0").hexdigest()
    plan = workflows.build_stage_capacity_plan_v1(
        stage_id=expected["stage_id"],
        logical_stage_id=context["logical_stage_id"],
        physical_attempt=context["physical_attempt"],
        physical_attempt_id=context["physical_attempt_id"],
        global_physical_attempt_ordinal=context[
            "global_physical_attempt_ordinal"
        ],
        logical_capacity_envelope_sha256=context[
            "logical_capacity_envelope_sha256"
        ],
        route_capability_snapshot_sha256=context[
            "route_capability_snapshot_sha256"
        ],
        stage="planning",
        contract_name=expected["contract_name"],
        contract_version=expected["contract_version"],
        contract_schema_sha256=expected["contract_schema_sha256"],
        provider_route_identity_sha256=context[
            "provider_route_identity_sha256"
        ],
        model_context_limit=context[
            "route_context_capability_limit_tokens"
        ],
        route_context_capability_source=context[
            "route_context_capability_source"
        ],
        external_workload_capacity_capability=context[
            "external_workload_capacity_capability"
        ],
        requested_output_token_cap=128,
        route_max_output_tokens=context["route_max_output_tokens"],
        final_output_reserve=128,
        rendered_message_tokens=31_920,
        structured_envelope_tokens=0,
        provider_envelope_tokens=256,
        wrapper_and_estimator_margin_tokens=1_024,
        rendered_request_sha256=rendered_request_sha256,
        layer_projections=(),
        parent_plan_sha256=None,
    )

    assert plan.admission_status.value == "PASS"
    assert plan.stage_operational_context_ceiling_tokens == 33_432
    assert plan.model_context_limit == 33_432
    assert plan.expected_rendered_input == 31_920
    assert (
        plan.expected_rendered_input
        + plan.provider_envelope_tokens
        + plan.wrapper_and_estimator_margin_tokens
    ) == 33_200
    assert plan.prompt_budget == 32_024
    assert workflows.StageCapacityAdmissionEngineV1.enforce(plan) is plan
    assert observer.bind_capacity_plan(
        plan=plan, route="primary", role="planning",
    ) == plan.plan_sha256
