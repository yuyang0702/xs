from __future__ import annotations

import copy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from novel_flywheel.db import Database
from novel_flywheel.domain.models import Message, ModelRequest
from novel_flywheel.canonical_shadow import canonical_sha256
from novel_flywheel.full_short_execution import (
    FullShortDispatchLedgerObserverV1,
    FullShortDurableExecutionStoreV1,
    FullShortExecutionPolicyV1,
    LOGICAL_STAGE_RECOVERY_POLICY_SHA256,
    LOGICAL_STAGE_RECOVERY_POLICY_V1,
    RESPONSE_CAPTURE_POLICY_V1,
    TRANSPORT_RECOVERY_POLICY_SHA256,
    TRANSPORT_RECOVERY_POLICY_V1,
    build_full_short_completion_receipt_v1,
    full_short_logical_stage_plan_sha256_v1,
)
from novel_flywheel.full_short_runtime_kernel import (
    DurableExecutionJournalV1,
    ExecutionState,
)
from novel_flywheel.providers.registry import ProviderRegistry
from novel_flywheel.project_transactions import canonical_json_sha256
from novel_flywheel.planning_semantics import (
    PlanningSemanticDraftV2,
    compile_planning_semantic_v2,
)
from novel_flywheel.quality import review_windows
from novel_flywheel.secrets import MemorySecretStore
from novel_flywheel.stage_capacity import build_stage_capacity_plan_v1
from novel_flywheel.short_canonical_promotion import (
    MaintenanceProposalInventoryV1,
    make_maintenance_inventory,
    proposal_units_from_candidate,
)
from tools.canary import execute_full_short_budget_unblocked_one_round as module
from tools.canary.execute_full_short_budget_unblocked_one_round import (
    EXPECTED_BRANCH,
    MandatoryGateReceiptsV1,
    OneRoundCampaignError,
    PostProbeAuthorizationV1,
    derive_post_probe_authorization_v1,
    execute_one_full_short_v1,
    materialize_campaign_authorization_v1,
    prepare_campaign_from_live_source_v1,
    preflight_campaign_v1,
    record_mandatory_gates_v1,
    run_probe_phase_v1,
)
from tools.canary.full_short_budget_unblocked_campaign import (
    GuardedRealCampaignResult,
    build_synthetic_probe_fixtures,
    run_offline_fake_campaign,
)


HEAD = "a" * 40
CORE_TREE = "f" * 64
KEY = b"orchestrator-test-verification-key-32-bytes-minimum"
KEY_ID = "campaign-test-key"
SOURCE_REPO = Path(__file__).resolve().parents[2]


def _seed_budget_sources(repo: Path) -> None:
    for relative in module._PINNED_BUDGET_SOURCE_SHA256S:
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SOURCE_REPO / relative, target)


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()


def _fixture_story_data() -> dict:
    return {
        "story_state_schema": 3,
        "outline": {
            "content": "The investigator verifies the archive clue.",
            "events": [{
                "id": "EV-00000001", "label": "Archive clue verified",
                "evidence": "The investigator verifies the archive clue.",
            }],
        },
        "ending": {
            "surface_goal": "The clue is published.",
            "inner_goal": "The investigator accepts the cost.",
            "cost": "An alliance ends.",
            "final_image": "Morning light reaches the archive.",
        },
        "confirmed_facts": [],
    }


def _durable_dry_chain(
    *, repo: Path, store_root: Path, runtime_authority: dict,
    project_workload: dict, final_bindings: dict, terminal: dict,
    maintenance_output_sha256: str, maintenance_receipt_sha256: str,
) -> tuple[dict, dict, bytes, dict]:
    execution_id = module.DRY_EXECUTION_ID
    store = FullShortDurableExecutionStoreV1(
        repo_root=repo, store_root=store_root,
    )
    provider_id = "offline-provider"
    model_id = "offline-model"
    route = {
        "role": "maintenance", "lane": "primary",
        "provider_id_sha256": hashlib.sha256(provider_id.encode()).hexdigest(),
        "provider_name": "offline", "provider_operator": "offline",
        "model_id_sha256": hashlib.sha256(model_id.encode()).hexdigest(),
        "model_name": "offline-model", "protocol": "anthropic",
        "route_fingerprint": "9" * 64,
        "destination": "https://unit.test:443/v1/messages",
        "max_output_tokens": 4096,
        "route_context_capability_limit_tokens": 32768,
        "route_context_capability_source": "model_configuration",
    }
    plan = ({
        "ordinal": 1, "stage_id": "maintenance",
        "logical_stage_base_id": "maintenance",
        "logical_stage_id": "maintenance", "role": "maintenance",
        "route_lane": "primary",
        "contract_name": "short_maintenance_business_complete_v2",
        "contract_version": 1, "contract_schema_sha256": "c" * 64,
        "contract_runtime_input_required": False,
        "requested_output_tokens": 128,
    },)
    egress = {
        "allowed": [
            "system_context", "task_contract", "authority", "story_slice",
            "current_baseline_skill_context", "output_contract",
            "provider_request_metadata",
        ],
        "forbidden": [
            "credentials", "unrelated_project_data", "raw_provider_evidence",
            "retired_skill_v3_hybrid_context",
        ],
    }
    policy = FullShortExecutionPolicyV1(
        execution_head=HEAD, branch=EXPECTED_BRANCH, run_id=execution_id,
        project_id_sha256=hashlib.sha256(b"2ad716f3c0d1").hexdigest(),
        workload_sha256=_hash(project_workload),
        runtime_authority_sha256=_hash(runtime_authority),
        style_reference_authority_sha256="e" * 64,
        route_manifest_sha256=_hash([route]),
        destination_manifest_sha256=_hash([route["destination"]]),
        egress_policy_sha256=_hash(egress),
        store_root_sha256=store.store_root_sha256,
        capture_attestation_public_key=store.capture_attestation_public_key,
        capture_attestation_public_key_sha256=(
            store.capture_attestation_public_key_sha256
        ),
        required_stage_roles=("maintenance",), logical_stage_plan=plan,
        expected_stage_calls=1, hard_max_provider_requests=2,
        hard_max_http_posts=2, hard_max_network_attempts=2,
        per_call_output_token_hard_cap=128,
        total_output_token_hard_cap=4096, maximum_elapsed_seconds=3600,
    ).document()
    architecture = (
        "failure_architecture_identity", "recovery_policy_registry",
        "recovery_policy_registry_sha256", "predispatch_state_machine",
        "predispatch_state_machine_sha256", "nonce_reservation_policy",
        "nonce_reservation_policy_sha256", "observer_isolation_policy",
        "observer_isolation_policy_sha256", "durable_failure_evidence_policy",
        "durable_failure_evidence_policy_sha256",
        "capacity_policy_registry_sha256",
    )
    public = {
        "project_id": "2ad716f3c0d1", "run_id": execution_id,
        "project_workload": project_workload,
        "runtime_authority": runtime_authority,
        "style_reference_authority": {}, "routes": [route],
        "destinations": [route["destination"]], "egress_policy": egress,
        "response_capture_policy": RESPONSE_CAPTURE_POLICY_V1,
        "capture_attestation_scheme": policy["capture_attestation_scheme"],
        "capture_attestation_public_key": store.capture_attestation_public_key,
        "capture_attestation_public_key_sha256": (
            store.capture_attestation_public_key_sha256
        ),
        "logical_stage_plan": policy["logical_stage_plan"],
        "logical_stage_plan_sha256": policy["logical_stage_plan_sha256"],
        "transport_recovery_policy": TRANSPORT_RECOVERY_POLICY_V1,
        "transport_recovery_policy_sha256": TRANSPORT_RECOVERY_POLICY_SHA256,
        "transport_recovery_policy_identity": "EXACT_REPLAY_ONLY",
        "logical_stage_recovery_policy": LOGICAL_STAGE_RECOVERY_POLICY_V1,
        "logical_stage_recovery_policy_sha256": (
            LOGICAL_STAGE_RECOVERY_POLICY_SHA256
        ),
        "logical_stage_recovery_policy_identity": (
            "TWO_SLOT_MUTUALLY_EXCLUSIVE_TYPED_RECOVERY"
        ),
        "store_root_sha256": store.store_root_sha256,
        **{field: policy[field] for field in architecture},
    }
    authorization_raw = module.render_full_short_canonical_authorization_v1(
        policy=policy, public_bindings=public,
    )
    permission = store.create_permission(
        execution_id=execution_id,
        authorization_text_sha256=hashlib.sha256(authorization_raw).hexdigest(),
        policy=policy, external_actions_enabled=False,
    )
    approval = store.create_jit_approval(
        execution_id=execution_id, policy=policy, permission=permission,
        external_actions_enabled=False,
    )
    nonce = store.reserve_nonce(
        execution_id=execution_id, policy=policy, approval=approval,
        external_actions_enabled=False,
    )
    observer = FullShortDispatchLedgerObserverV1(
        store=store, execution_id=execution_id, policy=policy,
        authorized_routes=(route,), egress_policy=egress,
    )
    observer.bind_stage_context(
        stage_id="maintenance",
        contract_name="short_maintenance_business_complete_v2",
        contract_version=1, contract_schema_sha256="c" * 64,
        contract_runtime_input_required=False,
    )
    context = observer.capacity_admission_context(
        route="primary", role="maintenance", physical_attempt=1,
    )
    rendered_sha = hashlib.sha256(b"\n\0").hexdigest()
    capacity_plan = build_stage_capacity_plan_v1(
        stage_id="maintenance", logical_stage_id="maintenance",
        physical_attempt=1, physical_attempt_id=context["physical_attempt_id"],
        global_physical_attempt_ordinal=1,
        logical_capacity_envelope_sha256=context[
            "logical_capacity_envelope_sha256"
        ],
        route_capability_snapshot_sha256=context[
            "route_capability_snapshot_sha256"
        ],
        stage="maintenance",
        contract_name="short_maintenance_business_complete_v2",
        contract_version=1, contract_schema_sha256="c" * 64,
        provider_route_identity_sha256=context[
            "provider_route_identity_sha256"
        ],
        model_context_limit=32768,
        route_context_capability_source="model_configuration",
        requested_output_token_cap=128, route_max_output_tokens=4096,
        final_output_reserve=128, reasoning_token_reserve=0,
        reasoning_token_accounting="INCLUDED_IN_COMPLETION_CAP",
        reasoning_output_reservation="WITHIN_COMPLETION_CAP",
        recovery_stage_role="NORMAL", reasoning_policy="DEFAULT",
        base_rendered_request_sha256=None, recovery_overlay_kind="NONE",
        prior_rendered_request_sha256=None,
        recovery_source_capture_receipt_sha256=None,
        rendered_message_tokens=0, structured_envelope_tokens=0,
        provider_envelope_tokens=256, wrapper_and_estimator_margin_tokens=1024,
        rendered_request_sha256=rendered_sha, layer_projections=(),
        parent_plan_sha256=None,
    )
    token = observer.bind_capacity_plan(
        plan=capacity_plan, route="primary", role="maintenance",
    )
    observer.authorize_capacity_dispatch_token(token)
    observer.bind_route(
        role="maintenance", lane="primary", provider_id=provider_id,
        model_id=model_id, route_fingerprint=route["route_fingerprint"],
    )
    observer.bind_model_request(
        protocol="anthropic", request=ModelRequest(
            model="offline-model", messages=[
                Message(role="system", content=""),
                Message(role="user", content=""),
            ],
            max_output_tokens=128,
        ),
    )
    payload = {
        "model": "offline-model",
        "messages": [{"role": "user", "content": ""}],
        "max_tokens": 128, "stream": True,
    }
    observer.before_http_dispatch(
        method="POST", url=route["destination"], payload=payload,
    )
    observer.capture_provider_protocol_input(
        data=b'{"content":[]}', status_code=200,
        content_type="application/json", encoding="utf-8",
        transport_complete=True,
    )
    observer.after_http_response(status_code=200)
    observer.mark_local_stage_complete(
        stage="maintenance", role="maintenance",
        role_binding_sha256=observer.bound_route["role_binding_sha256"],
        output_sha256=maintenance_output_sha256,
        receipt_sha256=maintenance_receipt_sha256,
    )
    ledger = store.load_ledger(execution_id)
    capacity_receipts = store.verify_completion_capacity_receipts(
        execution_id=execution_id, policy=policy, ledger=ledger,
    )
    completion = build_full_short_completion_receipt_v1(
        execution_id=execution_id, policy=policy, durable_store=store,
        permission_sha256=permission["permission_sha256"],
        signed_approval_sha256=approval["signed_approval_sha256"],
        nonce_sha256=nonce["nonce_sha256"], ledger=ledger,
        final_bindings=final_bindings, terminal_verification=terminal,
        capacity_admission_receipts=capacity_receipts,
    )
    store.commit_completion(
        execution_id=execution_id, policy=policy, receipt=completion,
    )
    runtime_path = store_root / f"{execution_id}.runtime-journal-v1.json"
    runtime = DurableExecutionJournalV1.create(
        runtime_path, execution_id=execution_id,
        initial_state=ExecutionState.TEMPLATE_READY,
    )
    for index, state in enumerate((
        ExecutionState.AUTHORIZED, ExecutionState.APPROVED,
        ExecutionState.PREDISPATCH_READY,
        ExecutionState.DISPATCH_TOKEN_RESERVED, ExecutionState.DISPATCHING,
        ExecutionState.RESPONSE_CAPTURED, ExecutionState.VALIDATING,
        ExecutionState.STAGE_ACCEPTED, ExecutionState.COMPLETED,
    ), 1):
        runtime.transition(
            state, transition_id=f"fixture-{index}",
            boundary_id="FS.CONTROL.PREFLIGHT",
        )
    return policy, public, authorization_raw, completion


def _fixture_project_document() -> dict:
    return {
        "id": "2ad716f3c0d1", "title": "Isolated Full Short",
        "mode": "short", "target_words": 13_000,
    }


_FIXTURE_CONSTRAINTS_BYTES = b"offline exact-ready constraints"


def _registry(tmp_path: Path) -> tuple[ProviderRegistry, Database]:
    db = Database(tmp_path / "app.db")
    db.migrate()
    registry = ProviderRegistry(db, MemorySecretStore())
    for provider_id, name, base_url, model in (
        ("87f5f31c-ef5d-4282-ae6f-86f4b335d9ff", "happy",
         "https://happyapi.org/v1", "qwen-3.7-plus"),
        ("68fd833c-17a5-4f45-830b-bd6dfa64d718", "lingsuan_sonnet",
         "https://lingsuan.org", "claude-sonnet-5"),
        ("247c0b35-b5ff-47a0-9793-9f9a6c663b08", "lingsuan_gpt",
         "https://lingsuan.org", "gpt-5.6-sol"),
    ):
        registry.add_provider(
            provider_id=provider_id, name=name, protocol="anthropic",
            base_url=base_url, api_key="offline-never-read",
        )
        registry.add_model(provider_id, model, model)
    return registry, db


def _dependencies(fixtures, *, store_root: Path, hard_max: int = 96):
    roles = {
        "draft": fixtures[0],
        "polish": fixtures[1],
        "planning": fixtures[2],
        "final_review": fixtures[5],
        "maintenance": fixtures[7],
    }
    routes = []
    for role, fixture in sorted(roles.items()):
        routes.append({
            "role": role,
            "lane": "primary",
            "provider_id_sha256": _hash(fixture.route.provider_id),
            "provider_name": fixture.route.provider,
            "provider_operator": fixture.route.operator,
            "model_id_sha256": _hash(fixture.route.model_id),
            "model_name": fixture.route.model,
            "protocol": fixture.route.protocol,
            "route_fingerprint": fixture.route.route_fingerprint,
            "destination": fixture.route.destination,
            "max_output_tokens": 32000,
            "route_context_capability_limit_tokens": 100000,
            "route_context_capability_source": "route_capability_registry",
        })
    logical_plan = []
    for index, fixture in enumerate(fixtures, 1):
        logical_plan.append({
            "ordinal": index,
            "stage_id": fixture.definition.family_id,
            "logical_stage_base_id": fixture.definition.family_id,
            "logical_stage_id": fixture.definition.family_id,
            "role": fixture.definition.role,
            "route_lane": "primary",
            "contract_name": fixture.definition.contract_name or "unstructured_text",
            "contract_version": 1,
            "contract_schema_sha256": "c" * 64,
            "contract_runtime_input_required": False,
            "requested_output_tokens": fixture.definition.wire_requested_output_cap,
        })
    egress = {
        "allowed": [
            "system_context", "task_contract", "authority", "story_slice",
            "current_baseline_skill_context", "output_contract",
            "provider_request_metadata",
        ],
        "forbidden": [
            "credentials", "unrelated_project_data", "raw_provider_evidence",
            "retired_skill_v3_hybrid_context",
        ],
    }
    store_root_sha = hashlib.sha256(
        str(store_root.resolve()).encode("utf-8")
    ).hexdigest()
    project_document = _fixture_project_document()
    project_json_sha256 = hashlib.sha256(
        module.canonical_json_bytes(project_document)
    ).hexdigest()
    project_workload = {
        "project_json_sha256": project_json_sha256,
        "constraints_sha256": hashlib.sha256(
            _FIXTURE_CONSTRAINTS_BYTES
        ).hexdigest(),
        "target_words": 13_000,
    }
    base_story_data = _fixture_story_data()
    base_story_sha = canonical_json_sha256(base_story_data)
    maintenance_source_sha = module.WorkflowService._text_hash(json.dumps(
        module.WorkflowService._short_maintenance_state_authority(
            base_story_data
        ),
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ))
    runtime_authority = {
        "story_state_revision": 6,
        "story_state_sha256": base_story_sha,
        "maintenance_source_state_sha256": maintenance_source_sha,
        "project_json_sha256": project_json_sha256,
    }
    policy = FullShortExecutionPolicyV1(
        execution_head=HEAD, branch=EXPECTED_BRANCH, run_id="one-round-test",
        project_id_sha256=hashlib.sha256(b"2ad716f3c0d1").hexdigest(),
        workload_sha256=_hash(project_workload),
        runtime_authority_sha256=_hash(runtime_authority),
        style_reference_authority_sha256="e" * 64,
        route_manifest_sha256=_hash(routes),
        destination_manifest_sha256=_hash(sorted({
            item["destination"] for item in routes
        })),
        egress_policy_sha256=_hash(egress), store_root_sha256=store_root_sha,
        capture_attestation_public_key="1" * 64,
        capture_attestation_public_key_sha256=hashlib.sha256(
            bytes.fromhex("1" * 64)
        ).hexdigest(),
        required_stage_roles=tuple(sorted(roles)),
        logical_stage_plan=tuple(logical_plan), expected_stage_calls=8,
        hard_max_provider_requests=hard_max,
        hard_max_http_posts=hard_max, hard_max_network_attempts=hard_max,
        per_call_output_token_hard_cap=32000,
        total_output_token_hard_cap=sum(
            item["requested_output_tokens"] for item in logical_plan
        ) + 3724,
        maximum_elapsed_seconds=36000,
    ).document()
    architecture = (
        "failure_architecture_identity", "recovery_policy_registry",
        "recovery_policy_registry_sha256", "predispatch_state_machine",
        "predispatch_state_machine_sha256", "nonce_reservation_policy",
        "nonce_reservation_policy_sha256", "observer_isolation_policy",
        "observer_isolation_policy_sha256", "durable_failure_evidence_policy",
        "durable_failure_evidence_policy_sha256", "capacity_policy_registry_sha256",
    )
    public = {
        "project_id": "2ad716f3c0d1", "run_id": "one-round-test",
        "project_workload": project_workload,
        "runtime_authority": runtime_authority,
        "style_reference_authority": {},
        "routes": routes,
        "destinations": sorted({item["destination"] for item in routes}),
        "egress_policy": egress,
        "response_capture_policy": RESPONSE_CAPTURE_POLICY_V1,
        "capture_attestation_scheme": policy["capture_attestation_scheme"],
        "capture_attestation_public_key": policy["capture_attestation_public_key"],
        "capture_attestation_public_key_sha256": policy[
            "capture_attestation_public_key_sha256"
        ],
        "logical_stage_plan": policy["logical_stage_plan"],
        "logical_stage_plan_sha256": policy["logical_stage_plan_sha256"],
        "transport_recovery_policy": TRANSPORT_RECOVERY_POLICY_V1,
        "transport_recovery_policy_sha256": TRANSPORT_RECOVERY_POLICY_SHA256,
        "transport_recovery_policy_identity": "EXACT_REPLAY_ONLY",
        "logical_stage_recovery_policy": LOGICAL_STAGE_RECOVERY_POLICY_V1,
        "logical_stage_recovery_policy_sha256": LOGICAL_STAGE_RECOVERY_POLICY_SHA256,
        "logical_stage_recovery_policy_identity": (
            "TWO_SLOT_MUTUALLY_EXCLUSIVE_TYPED_RECOVERY"
        ),
        "store_root_sha256": store_root_sha,
        **{field: policy[field] for field in architecture},
    }
    actual = {
        "head": HEAD, "branch": EXPECTED_BRANCH,
        "project_id_sha256": policy["project_id_sha256"],
        "workload_sha256": policy["workload_sha256"],
        "runtime_authority_sha256": policy["runtime_authority_sha256"],
        "style_reference_authority_sha256": policy[
            "style_reference_authority_sha256"
        ],
        "route_manifest_sha256": policy["route_manifest_sha256"],
        "destination_manifest_sha256": policy["destination_manifest_sha256"],
        "egress_policy_sha256": policy["egress_policy_sha256"],
        "store_root_sha256": store_root_sha,
        "capture_attestation_public_key": policy["capture_attestation_public_key"],
        "capture_attestation_public_key_sha256": policy[
            "capture_attestation_public_key_sha256"
        ],
        "response_capture_policy_sha256": policy[
            "response_capture_policy_sha256"
        ],
        "logical_stage_recovery_policy_sha256": policy[
            "logical_stage_recovery_policy_sha256"
        ],
        "failure_architecture_identity": policy["failure_architecture_identity"],
    }
    return policy, public, actual


def _patch_clean_git(monkeypatch):
    def fake_git(_repo, *args):
        if args == ("rev-parse", "HEAD"):
            return HEAD
        if args == ("branch", "--show-current"):
            return EXPECTED_BRANCH
        if args == ("status", "--porcelain"):
            return ""
        raise AssertionError(args)
    monkeypatch.setattr(module, "_git", fake_git)


def _materialized(tmp_path, monkeypatch, *, hard_max=96):
    _patch_clean_git(monkeypatch)
    registry, db = _registry(tmp_path)
    fixtures = build_synthetic_probe_fixtures(registry)
    store_root = tmp_path / "store"
    policy, public, actual = _dependencies(
        fixtures, store_root=store_root, hard_max=hard_max,
    )
    repo = tmp_path / "repo"
    repo.mkdir()
    _seed_budget_sources(repo)
    result = materialize_campaign_authorization_v1(
        repo=repo, evidence_root=tmp_path / "evidence", fixtures=fixtures,
        full_short_policy=policy, full_short_public_bindings=public,
        verification_key_id=KEY_ID, verification_key=KEY,
    )
    preflight_campaign_v1(
        result, repo=repo, data_dir=tmp_path, store_root=store_root,
        fixtures=fixtures, full_short_policy=policy,
        full_short_public_bindings=public,
        verification_key_id=KEY_ID, verification_key=KEY,
    )
    return result, repo, fixtures, db, policy, public, actual


def _offline_runner(fixtures, **kwargs):
    persist = kwargs.pop("persist")
    result = run_offline_fake_campaign(
        fixtures,
        authorization_sha256=kwargs["authorization_sha256"],
        final_execution_head=kwargs["final_execution_head"],
        key_id=kwargs["key_id"], signing_key=kwargs["signing_key"],
    )
    persist(result.campaign_state)
    return GuardedRealCampaignResult(
        campaign_state=result.campaign_state,
        raw_responses=result.raw_responses,
        sealed_evidence=result.sealed_evidence,
        verified_evidence=result.verified_evidence,
        promoted_evidence=result.promoted_evidence,
        transport_counters={"http_post_attempts": 8, "network_requests": 8},
        privacy_counts=result.privacy_counts,
    )


def _gate_artifacts(
    tmp_path, materialized, nested, verified_evidence,
    *, duplicate_role: bool = False,
):
    roles = [
        "capacity_segmentation_runtime",
        "authority_storystate_canon",
        "recovery_exact_once_capture_restart",
        "route_evidence_budget_privacy",
        "literary_visible_invariance_baseline_skill",
    ]
    if duplicate_role:
        roles[-1] = roles[0]
    state = module.CampaignJournalV1(
        materialized.evidence_root, materialized.authorization_sha256, KEY,
    ).load()
    binding = {
        "outer_authorization_sha256": materialized.authorization_sha256,
        "nested_authorization_sha256": nested.authorization_sha256,
        "probe_evidence_manifest_sha256": module._json_sha256(sorted(
            item.evidence_sha256 for item in verified_evidence
        )),
        "previous_journal_state_sha256": state["state_sha256"],
        "generated_at_unix_seconds": state["campaign_started_unix_seconds"],
    }
    required_artifacts = [
        "planning-semantic-v2.json", "short-causal-chain.json",
        "short-execution-index.json", "draft.md", "polish.md",
        "final-review-evidence.json", "quality-report.json",
        "draft-integrity.json",
    ]
    # Every fixture models a distinct single-use durable execution.  Reusing
    # the control-store path would correctly trip the production replay guard.
    raw_root = tmp_path / f"g{len(tuple(tmp_path.glob('g*')))}"
    raw_root.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)

    def raw_file(name, raw):
        path = (raw_root / name).resolve()
        path.write_bytes(raw)
        return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}

    def raw_json(name, value):
        return raw_file(name, module.canonical_json_bytes(value))

    project_id = "2ad716f3c0d1"
    execution_id = "private-current-project-dry-run"
    project_sha = hashlib.sha256(project_id.encode()).hexdigest()
    paragraphs = []
    while module.effective_han_characters("".join(paragraphs)) < 13_000:
        ordinal = len(paragraphs) + 1
        paragraphs.append(
            f"第{ordinal}次核验中，调查员对照封印、目录与旧档，确认线索来源，"
            "记录人物行动和状态变化，最终把完整结论交给见证人。"
        )
    final_text = "".join(paragraphs)
    final_artifact = raw_file(
        "dry-final-artifact.md", final_text.encode("utf-8"),
    )
    chapter = raw_file("dry-chapter.md", final_text.encode("utf-8"))
    formal_event = {
        "id": "EV-00000001", "label": "Archive clue verified",
        "evidence": "The investigator verifies the archive clue.",
    }
    story_data = _fixture_story_data()
    story_sha = canonical_json_sha256(story_data)
    canon = raw_json("dry-canon.json", {
        "facts": [], "state": {}, "world_rules": [], "timeline": [],
    })
    story_state = raw_json("dry-story-state.json", {
        "schema": "FullShortStoryStateAuthoritySnapshotV1", "version": 1,
        "project_id_sha256": project_sha, "revision": 7,
        "data": story_data, "authority_sha256": story_sha,
    })
    base_story_data = copy.deepcopy(story_data)
    base_story_data.pop("manuscript_revision", None)
    base_story_sha = canonical_json_sha256(base_story_data)
    base_story_state = raw_json("dry-base-story-state.json", {
        "schema": "FullShortBaseStoryStateAuthoritySnapshotV1", "version": 1,
        "project_id_sha256": project_sha, "revision": 6,
        "data": base_story_data, "authority_sha256": base_story_sha,
    })
    project_evidence = raw_json(
        "dry-project.json", _fixture_project_document(),
    )
    constraints_evidence = raw_file(
        "dry-constraints.md", _FIXTURE_CONSTRAINTS_BYTES,
    )
    maintenance_source_sha = module.WorkflowService._text_hash(json.dumps(
        module.WorkflowService._short_maintenance_state_authority(
            base_story_data
        ),
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ))
    ready_body = {
        "schema": "ShortCanonicalCommitReceiptV1", "version": 1,
        "lane": "short_canonical_v2", "outcome": "committed",
        "policy_version": "short-canonical-policy-v1",
        "canonical_gate_result": "eligible", "operational_readiness": "ready",
        "projection_diagnostics_hash": "1" * 64, "story_time": "2026-01-01",
        "source_artifact_hash": final_artifact["sha256"],
        "base_authority_revision": 6, "base_authority_hash": base_story_sha,
        "target_revision": 7, "target_authority_hash": story_sha,
        "candidate_hash": "3" * 64, "proposed_claim_batch_hash": "4" * 64,
        "evidence_envelope_set_hash": "5" * 64,
        "accepted_mutation_ids": [], "rejected_mutation_ids": [],
        "held_mutation_ids": [], "journal_saga_id": execution_id,
        "writer_plan_hash": "6" * 64, "journal_frozen_input_hash": "7" * 64,
        "commit_performed": True, "story_state_commit_count": 1,
    }
    ready_body["receipt_hash"] = canonical_sha256(
        "ShortCanonicalCommitReceiptV1", ready_body,
    )
    ready = raw_json("dry-ready.json", ready_body)
    gate_payload = {"lane": "short_canonical_v2"}
    journal = raw_json("dry-project-mutation-journal.json", {
        "version": 1, "status": "committed", "operation": "short-story",
        "run_id": execution_id, "project_id": project_id,
        "snapshot_path": "runs/private/snapshot", "source_authority_sha256": "8" * 64,
        "expected_story_state_revision": 6,
        "managed_paths": [
            "manuscript/story.md", "chapters/chapter-01.md", "memory/canon.json",
        ],
        "artifacts": [
            {"path": "manuscript/story.md", "sha256": final_artifact["sha256"]},
            {"path": "chapters/chapter-01.md", "sha256": chapter["sha256"]},
            {"path": "memory/canon.json", "sha256": canon["sha256"]},
        ],
        "story_state": {
            "candidate_id": "candidate", "expected_revision": 6,
            "target_revision": 7, "state_sha256": story_sha, "data": story_data,
        },
        "post_commit_gate": {
            "name": "short_canonical_v2_commit_v1",
            "payload_sha256": canonical_json_sha256(gate_payload),
            "payload": gate_payload, "status": "passed",
            "receipt_path": "runs/private/ready.json",
            "receipt_sha256": ready["sha256"],
        },
        "memory_effects": [], "learning_artifact_invalidations": [],
    })
    maintenance_candidate = {"facts": [{
            "key": "character.location.protagonist",
            "value": "courtyard",
            "evidence": "offline final artifact",
        }], "state": {},
        "coverage": {
            "manuscript_sha256": final_artifact["sha256"], "complete": True,
        },
        "disposition": "changes",
        "no_change_reason": "A durable location fact was extracted.",
    }
    maintenance_units = proposal_units_from_candidate(
        maintenance_candidate,
        source_mode="normal", source_locator="normal:attempt:1",
        source_attempt=1,
    )
    maintenance_inventory = make_maintenance_inventory(
        source_mode="normal",
        source_artifact_hash=final_artifact["sha256"],
        base_authority_revision=6,
        base_authority_hash=base_story_sha,
        units=maintenance_units,
    )
    maintenance = raw_json(
        "dry-maintenance-authority.json",
        maintenance_inventory.model_dump(mode="json", by_alias=True),
    )
    maintenance_inputs = [{
        "kind": "MaintenanceProposalInventoryV1",
        "sha256": maintenance["sha256"],
    }]
    maintenance_sha = module.domain_sha256(
        "novel-flywheel-short-maintenance-receipts-v1", maintenance_inputs,
    )
    maintenance_model_receipt = raw_json(
        "dry-maintenance-model-receipt.json", {"model": {
            "role": "maintenance", "provider_id": "offline-provider",
            "model_id": "offline-model", "route_fingerprint": "9" * 64,
        }},
    )
    maintenance_output = raw_json(
        "dry-maintenance-output.json", maintenance_candidate,
    )
    semantic_payload = {
        "version": 2,
        "initial_state": "The archive inquiry begins under sealed authority.",
        "segments": [{
            "kind": "terminal", "segment": 1,
            "title": "Archive verification",
            "events": [{
                "formal_event_ordinal": 1,
                "narrative": (
                    "The investigator verifies the archive clue and publishes "
                    "the result under the formal event contract."
                ),
            }],
        }],
    }
    semantic = PlanningSemanticDraftV2.model_validate(semantic_payload)
    compiled = compile_planning_semantic_v2(
        semantic, [formal_event], formal_ending=story_data["ending"],
        expected_segment_count=1,
    )
    causal = {
        "core_goal": "Publish the verified archive clue.",
        "opening": {"pressure": "The archive may close."},
        "cycles": [{
            "obstacle": "The index is inconsistent.",
            "effort": "The investigator compares the seals.",
            "result": "The authentic entry is identified.",
            "state_change": "The clue becomes publishable.",
        }],
        "accidents": [], "reversal": {},
        "ending": "The verified clue is published.",
        "question_chain": [], "relationship_arc": [],
        "covered_event_ids": ["EV-00000001"],
    }
    execution_manifest = {
        "version": 4, "status": "ready", "authority_sha256": "d" * 64,
        "outline_sha256": hashlib.sha256(
            story_data["outline"]["content"].encode("utf-8")
        ).hexdigest(),
        "planning_sha256": hashlib.sha256(
            compiled.plan.encode("utf-8")
        ).hexdigest(),
        "causal_chain_sha256": module._json_sha256(causal),
        "beats": [{
            "beat_id": "EV-00000001/01",
            "source_event_id": "EV-00000001", "order": 1,
            "action": "The investigator verifies the archive clue.",
            "preconditions": [], "postconditions": ["clue verified"],
            "owner_segment": 1, "source_evidence": formal_event["evidence"],
            "presentation_order": 1,
        }],
        "segments": [{
            "segment": 1, "beat_ids": ["EV-00000001/01"],
            "entry_state": [{
                "state": "archive inquiry open", "produced_by": [],
                "inherited_from": "formal opening authority",
            }],
            "exit_state": [{
                "state": "clue verified",
                "produced_by": ["EV-00000001/01"], "inherited_from": "",
            }],
            "previous_exit_sha256": "", "prohibited_future_beat_ids": [],
        }],
        "semantic_receipt": {}, "repair_attempts": 0,
    }
    expected_windows = review_windows(final_text)
    windows = [{
        "window": item["index"], "start": item["start"], "end": item["end"],
        "manuscript_sha256": final_artifact["sha256"],
        "window_sha256": hashlib.sha256(
            item["text"].encode("utf-8")
        ).hexdigest(),
        "summary": "The complete isolated manuscript was reviewed.",
        "issues": [],
    } for item in expected_windows]
    audit = {
        "coverage": 1.0, "window_count": len(windows),
        "reviewed_windows": len(windows), "reconciliations": [],
        "prior_issue_ids": [],
    }
    terminal_review = {
        "hard_fail": False, "decision": "pass", "issues": [],
        "score": 90, "scoring_profile_id": "zhihu-short-v2",
        "judge_signature": "offline/final-review",
    }
    execution_value = module.parse_execution_manifest(execution_manifest)
    execution_sha256 = module.execution_manifest_sha256(execution_value)
    semantic_evidence = final_text[:24]
    semantic_order_evidence = final_text[:80]
    segment_receipt = {
        "authority_sha256": execution_manifest["authority_sha256"],
        "execution_manifest_sha256": execution_sha256,
        "task_id": "segment-01",
        "prose_sha256": final_artifact["sha256"],
        "beat_receipts": [{
            "beat_id": "EV-00000001/01",
            "evidence": semantic_evidence,
            "actor_action_valid": True,
            "actor_action_evidence": semantic_evidence,
            "state_valid": True,
            "state_evidence": semantic_evidence,
            "scene_order_valid": True,
            "scene_order_evidence": semantic_order_evidence,
        }],
        "entry": {"satisfied": True, "evidence": semantic_evidence},
        "exit": {"satisfied": True, "evidence": final_text[-24:]},
        "outside_beat_ids": [], "future_beat_ids": [],
        "viewpoint_valid": True, "viewpoint_evidence": semantic_evidence,
        "causal_order_valid": True,
        "causal_order_evidence": semantic_order_evidence,
        "summary": "事件、状态、顺序与交接均已核对。",
    }
    whole_receipt = {
        "authority_sha256": execution_manifest["authority_sha256"],
        "draft_sha256": final_artifact["sha256"],
        "segment_sha256": [final_artifact["sha256"]],
        "event_ids": ["EV-00000001/01"],
        "missing_event_ids": [], "duplicate_event_ids": [],
        "out_of_order_event_ids": [], "causal_order_valid": True,
        "continuity_valid": True, "ending_valid": True,
        "commitments_valid": True,
        "evidence": [{"kind": "ending", "excerpt": final_text[-24:]}],
        "summary": "整篇事件、连续性与结局均已核对。",
    }
    narrative_integrity = {
        "status": "passed", "authority_sha256": execution_manifest["authority_sha256"],
        "draft_sha256": final_artifact["sha256"],
        "publication_sha256": final_artifact["sha256"],
        "publication_segment_lengths": [len(final_text)],
        "execution_manifest_sha256": execution_sha256,
        "segments": [{"text_sha256": final_artifact["sha256"]}],
        "semantic_segment_receipts": [segment_receipt],
        "whole_semantic_receipt": whole_receipt,
    }
    stage_values = {
        "planning-semantic-v2.json": semantic_payload,
        "short-causal-chain.json": causal,
        "short-execution-index.json": execution_manifest,
        "draft.md": final_text, "polish.md": final_text,
        "final-review-evidence.json": {"windows": windows, "audit": audit},
        "quality-report.json": {
            "status": "passed", "terminal_review_complete": True,
            "terminal_reviewed_hash": final_artifact["sha256"],
            "final_review_evidence": audit,
            "terminal_review": terminal_review,
            "best_attempt": 1, "best_score": 90,
            "scoring_profile_id": "zhihu-short-v2",
            "judge_signature": "offline/final-review",
        },
        "draft-integrity.json": narrative_integrity,
    }
    stage_artifacts = {}
    for name, value in sorted(stage_values.items()):
        raw = (
            module.canonical_json_bytes(value)
            if name.endswith(".json") else value.encode("utf-8")
        )
        stage_artifacts[name] = raw_file(f"dry-stage-{name}", raw)
    stage_artifacts_sha = module._json_sha256([
        {"name": name, "sha256": reference["sha256"]}
        for name, reference in sorted(stage_artifacts.items())
    ])
    quality_checkpoint = raw_json("dry-quality-checkpoint.json", {
        "version": 1, "manuscript_path": "outputs/best-candidate.md",
        "manuscript_hash": final_artifact["sha256"],
        "terminal_reviewed_hash": final_artifact["sha256"],
        "outcome": "passed", "score": 90, "best_attempt": 1,
        "scoring_profile_id": "zhihu-short-v2",
        "judge_signature": "offline/final-review",
        "review": terminal_review, "issue_ledger": [],
        "narrative_integrity": {
            "path": "outputs/draft-integrity.json",
            "sha256": stage_artifacts["draft-integrity.json"]["sha256"],
        },
    })
    terminal_body = {
        "schema": "ShortCompletionVerificationV1", "version": 1,
        "workflow_final_status": "completed",
        "unresolved_terminal_status": "none", "live_parity_status": "exact",
        "completion_goal_outcome": (
            "SHORT_WORKFLOW_COMPLETED_AND_FINAL_REVIEW_ACCEPTED"
        ),
        "final_manuscript_sha256": final_artifact["sha256"],
        "final_manuscript_binding_status": "exact",
        "final_review": {
            "accepted_status": "accepted", "binding_status": "exact",
        },
        "final_artifact": {"binding_status": "exact"},
        "maintenance": {
            "closure_status": "exact",
            "artifact_receipt_sha256": maintenance_sha,
            "project_mutation_journal_sha256": journal["sha256"],
        },
        "final_checkpoint": {
            "checkpoint_sha256": quality_checkpoint["sha256"],
            "binding_status": "exact", "closure_status": "exact",
        },
    }
    terminal_body["verification_receipt_sha256"] = module.domain_sha256(
        "novel-flywheel-short-completion-verification-v1", terminal_body,
    )
    terminal = raw_json("dry-terminal-verification.json", terminal_body)
    final_bindings = {
        "manuscript_sha256": final_artifact["sha256"],
        "chapter_sha256": chapter["sha256"], "canon_sha256": canon["sha256"],
        "story_state_sha256": story_sha,
        "quality_checkpoint_sha256": quality_checkpoint["sha256"],
        "terminal_verification_sha256": terminal_body[
            "verification_receipt_sha256"
        ],
    }
    dry_policy, dry_public, dry_authorization_raw, completion_body = (
        _durable_dry_chain(
            repo=repo, store_root=raw_root / "durable-control-store",
            runtime_authority=dict(nested.public_bindings["runtime_authority"]),
            project_workload=dict(nested.public_bindings["project_workload"]),
            final_bindings=final_bindings, terminal=terminal_body,
            maintenance_output_sha256=maintenance_output["sha256"],
            maintenance_receipt_sha256=maintenance_model_receipt["sha256"],
        )
    )
    completion = raw_json("dry-completion.json", completion_body)
    durable_root = raw_root / "durable-control-store"
    durable_store = FullShortDurableExecutionStoreV1(
        repo_root=repo, store_root=durable_root,
    )
    canonical_authorization = raw_file(
        "dry-canonical-authorization.json", dry_authorization_raw,
    )
    authorization_policy = raw_json(
        "dry-authorization-policy.json", dry_policy,
    )
    authorization_public = raw_json(
        "dry-authorization-public.json", dry_public,
    )
    control_store = {
        kind: raw_file(
            f"dry-durable-{kind}.json",
            durable_store._path(execution_id, kind).read_bytes(),
        )
        for kind in ("permission", "approval", "nonce", "ledger", "completion")
    }
    capacity_evidence = [
        raw_file(f"dry-capacity-{index:03d}.json", path.read_bytes())
        for index, path in enumerate(
            sorted(durable_store.capacity_receipt_root.glob("*.json")), 1,
        )
    ]
    anchor_evidence = [
        raw_file(f"dry-anchor-{index:03d}.json", path.read_bytes())
        for index, path in enumerate(
            sorted(durable_store.capture_anchor_root.glob("*.json")), 1,
        )
    ]
    capture_root = durable_root / "provider-response-captures-v1"
    capture_evidence = [{
        "relative_path": path.relative_to(capture_root).as_posix(),
        "evidence": raw_file(f"dry-capture-{index:03d}.bin", path.read_bytes()),
    } for index, path in enumerate(
        sorted(item for item in capture_root.rglob("*") if item.is_file()), 1,
    )]
    runtime_journal = raw_file(
        "dry-runtime-journal.json",
        (durable_root / f"{execution_id}.runtime-journal-v1.json").read_bytes(),
    )
    replay_proof = raw_json("dry-replay-proof.json", {
        "all_captured_synthetic_responses_exactly_replayable": True,
        "replayed_full_workflow_matches_final_artifact": True,
    })
    authority_bindings = {
        "completion_receipt_sha256": completion_body["completion_receipt_sha256"],
        "terminal_verification_sha256": terminal_body["verification_receipt_sha256"],
        "final_artifact_sha256": final_artifact["sha256"],
        "chapter_sha256": chapter["sha256"], "story_state_sha256": story_sha,
        "canon_sha256": canon["sha256"], "ready_receipt_sha256": ready["sha256"],
        "project_mutation_journal_sha256": journal["sha256"],
        "maintenance_artifact_receipt_sha256": maintenance_sha,
        "required_stage_artifacts_sha256": stage_artifacts_sha,
        "runtime_authority_sha256": nested.policy[
            "runtime_authority_sha256"
        ],
        "workload_sha256": nested.policy["workload_sha256"],
        "project_json_sha256": project_evidence["sha256"],
        "constraints_sha256": constraints_evidence["sha256"],
        "quality_checkpoint_sha256": quality_checkpoint["sha256"],
        "narrative_integrity_sha256": stage_artifacts[
            "draft-integrity.json"
        ]["sha256"],
    }
    dry_manifest = raw_json("dry-isolated-manifest.json", {
        "schema": "FullShortIsolatedDryRunEvidenceManifestV2", "version": 2,
        "source_head": HEAD, "project_id_sha256": project_sha,
        "execution_id": execution_id,
        "execution_id_sha256": hashlib.sha256(execution_id.encode()).hexdigest(),
        "durable_store": {
            "root": str(durable_root.resolve()),
            "store_root_sha256": durable_store.store_root_sha256,
        },
        "authority_bindings": authority_bindings,
        "receipts": {
            "completion": completion, "terminal_verification": terminal,
            "final_artifact": final_artifact, "chapter": chapter,
            "story_state": story_state, "canon": canon, "ready": ready,
            "project_mutation_journal": journal,
            "maintenance_receipts": [{
                "kind": "MaintenanceProposalInventoryV1", "evidence": maintenance,
            }],
            "maintenance_model_receipt": maintenance_model_receipt,
            "maintenance_output": maintenance_output,
            "stage_artifacts": stage_artifacts,
            "base_story_state": base_story_state,
            "project": project_evidence,
            "constraints": constraints_evidence,
            "quality_checkpoint": quality_checkpoint,
            "narrative_integrity": stage_artifacts["draft-integrity.json"],
            "canonical_authorization": canonical_authorization,
            "authorization_policy": authorization_policy,
            "authorization_public_bindings": authorization_public,
            "runtime_journal": runtime_journal,
            "replay_proof": replay_proof,
            "control_store": control_store,
            "capacity_admission_receipts": capacity_evidence,
            "capture_anchors": anchor_evidence,
            "provider_response_captures": capture_evidence,
        },
        "maintenance_authority": {
            "base_story_state_revision": 6,
            "base_story_state_sha256": base_story_sha,
            "live_story_state_revision": 7,
            "live_story_state_sha256": story_sha,
            "maintenance_source_state_sha256": maintenance_source_sha,
            "source_modes": ["normal"],
            "normal_lane_exact": True,
            "reduction_lane_exact": False,
        },
        "external_actions": {
            "credential_lookup": 0, "provider_client_creation": 0,
            "provider_request": 0, "http_post": 0, "network": 0,
            "model": 0, "paid": 0,
        },
        "private_isolated_evidence": True,
    })
    dry_output = raw_json("dry-output.json", {
        "schema": "FirstTrustworthyFullShortPrivateDryRunV2",
        "version": 2, "status": "PASS", "pass": True,
        "source_head": HEAD, "project_id_sha256": project_sha,
        "runtime_authority_sha256": nested.policy[
            "runtime_authority_sha256"
        ],
        "workload_sha256": nested.policy["workload_sha256"],
        "workflow_status": "completed",
        "completion_goal_outcome": (
            "SHORT_WORKFLOW_COMPLETED_AND_FINAL_REVIEW_ACCEPTED"
        ),
        "completion_receipt_sha256": completion_body["completion_receipt_sha256"],
        "final_artifact_sha256": final_artifact["sha256"],
        "isolated_evidence_manifest": dry_manifest,
        "isolated_gate_evidence_persisted": True,
        "all_required_stage_roles_completed": True,
        "all_dispatches_locally_closed": True,
        "completed_stage_roles": [
            "planning", "draft", "review", "polish", "final_review",
        ],
        "dry_run_artifacts_cannot_be_mistaken_for_real_output": True,
        "real_credential_lookup_count": 0,
        "real_provider_client_creation_count": 0,
        "real_provider_request_attempts": 0,
        "real_http_post_attempts": 0, "real_network_calls": 0,
        "real_model_calls": 0, "paid_calls": 0,
    })
    artifacts = [{
        "schema": "FullShortExactReadyDryRunGateSourceV2",
        "dry_run_output": dry_output,
        "isolated_evidence_manifest": dry_manifest,
        **binding,
    }]
    records = []
    for target in (13_000, 20_000, 30_000):
        payload = raw_file(
            f"size-payload-{target}.json",
            json.dumps({"model": "offline-large", "target": target}).encode(),
        )
        records.append({
            "target_words": target,
            "pytest_node_id": (
                "tests/test_workflows.py::test_full_short_real_http_seam"
                f"[{target}]"
            ),
            "status": "passed", "workflow_status": "completed",
            "actual_effective_han_characters": target,
            "segmentation_behavior": "PASS",
            "required_roles_completed": True,
            "required_artifacts_present": True,
            "completion_goal_outcome": (
                "SHORT_WORKFLOW_COMPLETED_AND_FINAL_REVIEW_ACCEPTED"
            ),
            "provider_wire_envelopes": [{
                "model_name": "offline-large",
                "estimated_input_tokens": 10_000,
                "requested_output_tokens": 8_000,
                "context_limit_tokens": 262_144,
                "max_output_tokens": 32_768,
                "payload_bytes": (raw_root / f"size-payload-{target}.json").stat().st_size,
                "payload_sha256": payload["sha256"],
                "payload_evidence": payload,
            }],
        })
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(exist_ok=True)
    shutil.copyfile(SOURCE_REPO / "tests/test_workflows.py", repo / "tests/test_workflows.py")
    (repo / "src").mkdir(exist_ok=True)
    (repo / "src/review-core.py").write_text("CORE = True\n", encoding="utf-8")
    (repo / "tests/review-test.py").write_text("def test_core(): pass\n", encoding="utf-8")
    junit = raw_file("size-junit.xml", (
        '<testsuite tests="3" failures="0" errors="0" skipped="0">'
        + "".join(
            f'<testcase classname="tests.test_workflows" name="test_full_short_real_http_seam[{target}]" />'
            for target in (13_000, 20_000, 30_000)
        ) + "</testsuite>"
    ).encode())
    envelope_manifest = raw_json("size-envelope-manifest.json", {
        "schema": "FullShortHttpSeamEnvelopeManifestV1", "version": 1,
        "source_head": HEAD,
        "test_path": "tests/test_workflows.py::test_full_short_real_http_seam",
        "test_file_sha256": hashlib.sha256(
            (repo / "tests/test_workflows.py").read_bytes()
        ).hexdigest(),
        "junit_xml_sha256": junit["sha256"], "run_records": records,
    })
    artifacts.append({
        "schema": "FullShortSizeMatrixGateSourceV2",
        "junit_xml": junit, "envelope_manifest": envelope_manifest, **binding,
    })
    baseline = raw_json("strict-baseline.json", {
        "version": 1, "repository": str(repo.resolve()), "state": {},
    })
    forward_value = {
        "version": 2, "constraint_traceability": [{"requirement": "raw gates"}],
    }
    forward = raw_json("strict-forward-risk.json", forward_value)
    core_tree = module._core_review_sha256_v1(repo, ["src/review-core.py"])
    inspection = raw_json("strict-inspection-stdout.json", {
        "ok": True, "warnings": [], "blockers": [],
        "baseline_used": True, "recommended_level": "L3",
        "core_paths": ["src/review-core.py"],
        "forward_risk_report": forward_value, "split_review_report": None,
    })
    artifacts.append({
        "schema": "FullShortStrictL3GateSourceV2",
        "inspection_stdout_json": inspection,
        "baseline": baseline, "forward_risk_report": forward,
        **binding,
    })
    core_sha = hashlib.sha256((repo / "src/review-core.py").read_bytes()).hexdigest()
    test_sha = hashlib.sha256((repo / "tests/review-test.py").read_bytes()).hexdigest()
    for index, role in enumerate(roles, 1):
        test_run = raw_file(f"review-{index}-tests.txt", b"1 passed\n")
        identity = f"fresh-review-agent-{index}"
        report = raw_json(f"review-{index}-report.json", {
            "schema": "FullShortArchitectureReviewArtifactV2", "version": 2,
            "final_execution_head": HEAD, "core_tree_sha256": core_tree,
            "reviewer_role": role, "reviewer_agent_identity": identity,
            "reviewer_agent_identity_sha256": hashlib.sha256(identity.encode()).hexdigest(),
            "status": "ARCHITECTURE_PASS", "findings": [],
            "reviewed_core_paths": ["src/review-core.py"],
            "reviewed_files": [{"path": "src/review-core.py", "sha256": core_sha}],
            "test_files": [{"path": "tests/review-test.py", "sha256": test_sha}],
            "test_run_evidence": test_run,
        })
        artifacts.append({
            "schema": "FullShortArchitectureReviewGateSourceV2",
            "review_report": report, **binding,
        })
    evidence_paths = []
    for index, artifact in enumerate(artifacts):
        path = tmp_path / f"source-gate-evidence-{index + 1}.json"
        path.write_bytes(module.canonical_json_bytes(artifact))
        evidence_paths.append(path.resolve())
    return tuple(evidence_paths)


def _rewrite_dry_manifest_source(
    source_path: Path, mutate,
) -> None:
    source = json.loads(source_path.read_text(encoding="utf-8"))
    manifest_reference = source["isolated_evidence_manifest"]
    manifest_path = Path(manifest_reference["path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    mutate(manifest)
    manifest_raw = module.canonical_json_bytes(manifest)
    manifest_path.write_bytes(manifest_raw)
    manifest_reference["sha256"] = hashlib.sha256(manifest_raw).hexdigest()
    source["isolated_evidence_manifest"] = manifest_reference

    dry_reference = source["dry_run_output"]
    dry_path = Path(dry_reference["path"])
    dry = json.loads(dry_path.read_text(encoding="utf-8"))
    dry["isolated_evidence_manifest"] = manifest_reference
    dry["completion_receipt_sha256"] = manifest["authority_bindings"][
        "completion_receipt_sha256"
    ]
    dry["final_artifact_sha256"] = manifest["authority_bindings"][
        "final_artifact_sha256"
    ]
    dry_raw = module.canonical_json_bytes(dry)
    dry_path.write_bytes(dry_raw)
    dry_reference["sha256"] = hashlib.sha256(dry_raw).hexdigest()
    source["dry_run_output"] = dry_reference
    source_path.write_bytes(module.canonical_json_bytes(source))


def _post_probe_public(public, actual, evidence):
    post_public = copy.deepcopy(public)
    by_route = {}
    for item in evidence:
        key = (
            item.provider, item.operator, item.destination, item.protocol,
            item.model, item.route_fingerprint_sha256,
        )
        by_route.setdefault(key, []).append({
            "evidence_sha256": item.evidence_sha256,
        })
    for route in post_public["routes"]:
        key = (
            route["provider_name"], route["provider_operator"],
            route["destination"], route["protocol"], route["model_name"],
            route["route_fingerprint"],
        )
        route["external_workload_evidence_families"] = by_route.get(key, [])
    post_public["authorization_eligible"] = True
    post_actual = dict(actual)
    post_actual["route_manifest_sha256"] = _hash(post_public["routes"])
    return post_public, post_actual


def _ready_full_short(tmp_path, monkeypatch):
    materialized, repo, fixtures, db, policy, public, actual = (
        _materialized(tmp_path, monkeypatch)
    )
    probes = run_probe_phase_v1(
        materialized, repo=repo, fixtures=fixtures, db=db,
        store_root=tmp_path / "store",
        verification_key_id=KEY_ID, verification_key=KEY,
        runner=_offline_runner,
    )
    post_public, post_actual = _post_probe_public(
        public, actual, probes.verified_evidence,
    )
    monkeypatch.setattr(
        module, "collect_live_bindings",
        lambda **_kwargs: (post_actual, post_public),
    )
    nested = derive_post_probe_authorization_v1(
        materialized, repo=repo, data_dir=tmp_path,
        store_root=tmp_path / "store", template_policy=policy,
        verified_evidence=probes.verified_evidence,
        verification_key_id=KEY_ID, verification_key=KEY,
    )
    record_mandatory_gates_v1(
        materialized, nested, repo=repo,
        verified_evidence=probes.verified_evidence,
        verification_key_id=KEY_ID, verification_key=KEY,
        gate_evidence_paths=_gate_artifacts(
            tmp_path, materialized, nested, probes.verified_evidence,
        ),
    )
    return materialized, nested, repo, probes


def test_materialization_and_preflight_are_external_clean_and_unused(
    tmp_path, monkeypatch,
) -> None:
    materialized, _repo, _fixtures, _db, _policy, _public, _actual = (
        _materialized(tmp_path, monkeypatch)
    )
    assert materialized.evidence_root == (tmp_path / "evidence").resolve()
    assert materialized.authorization["campaign_usage"]["nonces_created"] == 0
    assert materialized.authorization["production_bindings"][
        "post_probe_authorization_derivation"
    ]["derivation_count_maximum"] == 1
    states = sorted(materialized.evidence_root.glob("campaign-state-*.json"))
    assert len(states) == 2
    preflight = json.loads(states[-1].read_text())
    assert preflight["phase"] == "PREFLIGHT_PASS"
    collision_raw = (
        materialized.evidence_root
        / "full-short-run-collision-absence-v1.json"
    ).read_bytes()
    collision = json.loads(collision_raw)
    assert collision["schema"] == "FullShortRunCollisionAbsenceReceiptV1"
    assert collision["matching_run_state_count"] == 0
    assert collision["real_execution_state_absent"] is True
    assert preflight["evidence"][
        "full_short_run_collision_absence_receipt_sha256"
    ] == hashlib.sha256(collision_raw).hexdigest()
    assert not (tmp_path / "store").exists()


@pytest.mark.parametrize(
    "kind",
    ["permission", "approval", "nonce", "ledger", "completion", "runtime"],
)
def test_probe_gate_rejects_each_durable_run_identity_before_runner(
    tmp_path, monkeypatch, kind,
) -> None:
    materialized, repo, fixtures, db, *_ = _materialized(
        tmp_path, monkeypatch,
    )
    store_root = tmp_path / "store"
    store_root.mkdir()
    storage_key = module.domain_sha256(
        "full-short-execution-storage-key-v1", "one-round-test",
    )
    path = (
        store_root / "one-round-test.runtime-journal-v1.json"
        if kind == "runtime"
        else store_root / f"{storage_key}.{kind}.json"
    )
    path.write_text("{}", encoding="utf-8")
    called = False

    def should_not_run(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError

    with pytest.raises(OneRoundCampaignError, match="RUN_ID_COLLISION"):
        run_probe_phase_v1(
            materialized, repo=repo, fixtures=fixtures, db=db,
            store_root=store_root,
            verification_key_id=KEY_ID, verification_key=KEY,
            runner=should_not_run,
        )
    assert called is False


def test_probe_gate_rejects_database_execution_state(
    tmp_path, monkeypatch,
) -> None:
    materialized, repo, fixtures, db, *_ = _materialized(
        tmp_path, monkeypatch,
    )
    with db.connect() as connection:
        connection.execute(
            "INSERT INTO projects VALUES (?, ?, ?, ?, datetime('now'))",
            ("2ad716f3c0d1", "fixture", "short", str(tmp_path / "project")),
        )
    db.create_run(
        "one-round-test", "2ad716f3c0d1", "short-story", status="queued",
    )
    with pytest.raises(OneRoundCampaignError, match="RUN_ID_COLLISION"):
        run_probe_phase_v1(
            materialized, repo=repo, fixtures=fixtures, db=db,
            store_root=tmp_path / "store",
            verification_key_id=KEY_ID, verification_key=KEY,
            runner=lambda *_args, **_kwargs: pytest.fail("runner called"),
        )


def test_probe_gate_rejects_auxiliary_store_execution_state(
    tmp_path, monkeypatch,
) -> None:
    materialized, repo, fixtures, db, *_ = _materialized(
        tmp_path, monkeypatch,
    )
    auxiliary = tmp_path / "store" / "capacity-v1" / "untrusted.json"
    auxiliary.parent.mkdir(parents=True)
    auxiliary.write_bytes(module.canonical_json_bytes({
        "schema": "any",
        "execution_id": "one-round-test",
    }))
    with pytest.raises(OneRoundCampaignError, match="RUN_ID_COLLISION"):
        run_probe_phase_v1(
            materialized, repo=repo, fixtures=fixtures, db=db,
            store_root=tmp_path / "store",
            verification_key_id=KEY_ID, verification_key=KEY,
            runner=lambda *_args, **_kwargs: pytest.fail("runner called"),
        )


def test_frozen_budget_derivation_binds_three_sources_and_live_fixtures(
    tmp_path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _seed_budget_sources(repo)
    registry, _db = _registry(tmp_path)
    fixtures = build_synthetic_probe_fixtures(registry)
    derived = module.derive_frozen_budget_v1(repo, fixtures)
    assert derived["exact_probe_fixture_input_tokens"] == 186_733
    assert derived["maximum_typed_business_recovery_path_physical_calls"] == 96
    assert derived["maximum_typed_business_recovery_path_provider_wire_input"] == 2_373_076
    assert derived["exact_pre_dispatch_estimated_input_tokens"] == 2_559_809
    assert derived["plan_derived_max_input_tokens"] == 3_071_771
    assert {
        derived["budget_recalculation_source"]["sha256"],
        derived["authoritative_attempt_matrix_source"]["sha256"],
        derived["probe_family_derivation_source"]["sha256"],
    } == set(module._PINNED_BUDGET_SOURCE_SHA256S.values())


def test_frozen_budget_derivation_rejects_committed_source_byte_drift(
    tmp_path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _seed_budget_sources(repo)
    path = repo / module._BUDGET_RECALCULATION_PATH
    path.write_bytes(path.read_bytes() + b" ")
    registry, _db = _registry(tmp_path)
    with pytest.raises(OneRoundCampaignError, match="BUDGET_DERIVATION_SOURCE_DRIFT"):
        module.derive_frozen_budget_v1(
            repo, build_synthetic_probe_fixtures(registry),
        )


def test_frozen_budget_derivation_rejects_live_fixture_estimate_drift(
    tmp_path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _seed_budget_sources(repo)
    registry, _db = _registry(tmp_path)
    fixtures = list(build_synthetic_probe_fixtures(registry))
    fixtures[0] = replace(
        fixtures[0],
        definition=replace(
            fixtures[0].definition,
            estimated_input_tokens=(
                fixtures[0].definition.estimated_input_tokens + 1
            ),
        ),
    )
    with pytest.raises(OneRoundCampaignError, match="BUDGET_DERIVATION_PROBE_DRIFT"):
        module.derive_frozen_budget_v1(repo, fixtures)


def test_single_preparation_entry_uses_credential_free_outer_projection(
    tmp_path, monkeypatch,
) -> None:
    _patch_clean_git(monkeypatch)
    registry, _db = _registry(tmp_path)
    fixtures = build_synthetic_probe_fixtures(registry)
    store_root = tmp_path / "prepared-store"
    policy, public, actual = _dependencies(fixtures, store_root=store_root)
    actual["external_action_counters"] = {
        "credential_lookup": 0, "provider_client_creation": 0,
        "provider_request": 0, "http_post": 0, "network": 0,
        "model": 0, "paid": 0,
    }
    calls = []

    def collect(**kwargs):
        calls.append(kwargs)
        assert kwargs["outer_authorization_projection"] is True
        assert "verified_external_workload_evidence" not in kwargs
        return actual, public

    monkeypatch.setattr(module, "collect_live_bindings", collect)
    repo = tmp_path / "repo"
    repo.mkdir()
    _seed_budget_sources(repo)
    prepared = prepare_campaign_from_live_source_v1(
        repo=repo, data_dir=tmp_path,
        evidence_root=tmp_path / "prepared-evidence",
        store_root=store_root,
        logical_stage_plan=policy["logical_stage_plan"],
        run_id="one-round-test", verification_key_id=KEY_ID,
        verification_key=KEY, expected_final_head=HEAD,
    )
    assert len(calls) == 1
    assert prepared.authorization["frozen_execution"]["worktree"] == "CLEAN"
    assert prepared.authorization["campaign_usage"]["provider_requests"] == 0


def test_preparation_accepts_95_stage_plan_under_derived_96_call_cap(
    tmp_path, monkeypatch,
) -> None:
    _patch_clean_git(monkeypatch)
    registry, _db = _registry(tmp_path)
    fixtures = build_synthetic_probe_fixtures(registry)
    store_root = tmp_path / "prepared-store"
    _policy, public, actual = _dependencies(fixtures, store_root=store_root)
    plan = [{
        "ordinal": ordinal,
        "stage_id": f"draft-part-{ordinal:03d}",
        "logical_stage_base_id": f"draft-part-{ordinal:03d}",
        "logical_stage_id": f"draft-part-{ordinal:03d}",
        "role": "draft", "route_lane": "primary",
        "contract_name": "unstructured_text", "contract_version": 1,
        "contract_schema_sha256": "c" * 64,
        "contract_runtime_input_required": False,
        "requested_output_tokens": 1,
    } for ordinal in range(1, 96)]
    public = copy.deepcopy(public)
    public["logical_stage_plan"] = plan
    public["logical_stage_plan_sha256"] = (
        full_short_logical_stage_plan_sha256_v1(plan)
    )
    actual["external_action_counters"] = {
        "credential_lookup": 0, "provider_client_creation": 0,
        "provider_request": 0, "http_post": 0, "network": 0,
        "model": 0, "paid": 0,
    }
    monkeypatch.setattr(
        module, "collect_live_bindings",
        lambda **_kwargs: (actual, public),
    )
    repo = tmp_path / "repo"
    repo.mkdir()
    _seed_budget_sources(repo)
    prepared = prepare_campaign_from_live_source_v1(
        repo=repo, data_dir=tmp_path,
        evidence_root=tmp_path / "prepared-evidence",
        store_root=store_root, logical_stage_plan=plan,
        run_id="one-round-test", verification_key_id=KEY_ID,
        verification_key=KEY, expected_final_head=HEAD,
    )
    policy = prepared.preprobe_full_short_policy
    assert policy["expected_stage_calls"] == 95
    assert policy["hard_max_provider_requests"] == 96
    assert policy["hard_max_http_posts"] == 96
    assert policy["hard_max_network_attempts"] == 96


def test_probe_reservation_is_durable_and_never_redispatches_after_uncertainty(
    tmp_path, monkeypatch,
) -> None:
    materialized, repo, fixtures, db, *_ = _materialized(tmp_path, monkeypatch)
    calls = 0

    def uncertain(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise RuntimeError("offline uncertainty")

    with pytest.raises(RuntimeError, match="uncertainty"):
        run_probe_phase_v1(
            materialized, repo=repo, fixtures=fixtures, db=db,
            store_root=tmp_path / "store",
            verification_key_id=KEY_ID, verification_key=KEY,
            runner=uncertain,
        )
    with pytest.raises(OneRoundCampaignError, match="NOT_ELIGIBLE"):
        run_probe_phase_v1(
            materialized, repo=repo, fixtures=fixtures, db=db,
            store_root=tmp_path / "store",
            verification_key_id=KEY_ID, verification_key=KEY,
            runner=uncertain,
        )
    assert calls == 1


def test_hmac_journal_tamper_and_post_preflight_fixture_drift_fail_closed(
    tmp_path, monkeypatch,
) -> None:
    materialized, repo, fixtures, db, *_ = _materialized(tmp_path, monkeypatch)
    calls = 0

    def should_not_run(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError

    with pytest.raises(OneRoundCampaignError, match="FIXTURE_MANIFEST_DRIFT"):
        run_probe_phase_v1(
            materialized, repo=repo, fixtures=tuple(reversed(fixtures)), db=db,
            store_root=tmp_path / "store",
            verification_key_id=KEY_ID, verification_key=KEY,
            runner=should_not_run,
        )
    state_path = sorted(
        materialized.evidence_root.glob("campaign-state-*.json")
    )[-1]
    state = json.loads(state_path.read_text())
    state["phase"] = "TAMPERED"
    state_path.write_bytes(module.canonical_json_bytes(state))
    with pytest.raises(OneRoundCampaignError, match="JOURNAL_INVALID"):
        run_probe_phase_v1(
            materialized, repo=repo, fixtures=fixtures, db=db,
            store_root=tmp_path / "store",
            verification_key_id=KEY_ID, verification_key=KEY,
            runner=should_not_run,
        )
    assert calls == 0


def test_exact_outer_evidence_manifest_is_checked_before_capacity_collection(
    tmp_path, monkeypatch,
) -> None:
    materialized, repo, fixtures, db, policy, _public, _actual = (
        _materialized(tmp_path, monkeypatch)
    )
    probes = run_probe_phase_v1(
        materialized, repo=repo, fixtures=fixtures, db=db,
        store_root=tmp_path / "store",
        verification_key_id=KEY_ID, verification_key=KEY,
        runner=_offline_runner,
    )
    forged = copy.copy(probes.verified_evidence[0])
    object.__setattr__(forged, "case_id", "substituted-case")
    called = False

    def should_not_collect(**_kwargs):
        nonlocal called
        called = True
        raise AssertionError

    monkeypatch.setattr(module, "collect_live_bindings", should_not_collect)
    with pytest.raises(OneRoundCampaignError, match="NOT_AUTHORIZED"):
        derive_post_probe_authorization_v1(
            materialized, repo=repo, data_dir=tmp_path,
            store_root=tmp_path / "store", template_policy=policy,
            verified_evidence=(forged, *probes.verified_evidence[1:]),
            verification_key_id=KEY_ID, verification_key=KEY,
        )
    assert called is False


def test_cumulative_probe_plus_full_short_caps_fail_closed(
    tmp_path, monkeypatch,
) -> None:
    materialized, repo, fixtures, db, policy, public, actual = (
        _materialized(tmp_path, monkeypatch, hard_max=137)
    )
    probes = run_probe_phase_v1(
        materialized, repo=repo, fixtures=fixtures, db=db,
        store_root=tmp_path / "store",
        verification_key_id=KEY_ID, verification_key=KEY,
        runner=_offline_runner,
    )
    post_public, post_actual = _post_probe_public(
        public, actual, probes.verified_evidence,
    )
    monkeypatch.setattr(
        module, "collect_live_bindings",
        lambda **_kwargs: (post_actual, post_public),
    )
    with pytest.raises(OneRoundCampaignError, match="HARD_CAP"):
        derive_post_probe_authorization_v1(
            materialized, repo=repo, data_dir=tmp_path,
            store_root=tmp_path / "store", template_policy=policy,
            verified_evidence=probes.verified_evidence,
            verification_key_id=KEY_ID, verification_key=KEY,
        )


@pytest.mark.asyncio
async def test_all_gates_allow_exactly_one_full_short_and_no_replacement(
    tmp_path, monkeypatch,
) -> None:
    materialized, repo, fixtures, db, policy, public, actual = (
        _materialized(tmp_path, monkeypatch)
    )
    probes = run_probe_phase_v1(
        materialized, repo=repo, fixtures=fixtures, db=db,
        store_root=tmp_path / "store",
        verification_key_id=KEY_ID, verification_key=KEY,
        runner=_offline_runner,
    )
    post_public, post_actual = _post_probe_public(
        public, actual, probes.verified_evidence,
    )
    monkeypatch.setattr(
        module, "collect_live_bindings",
        lambda **_kwargs: (post_actual, post_public),
    )
    nested = derive_post_probe_authorization_v1(
        materialized, repo=repo, data_dir=tmp_path,
        store_root=tmp_path / "store", template_policy=policy,
        verified_evidence=probes.verified_evidence,
        verification_key_id=KEY_ID, verification_key=KEY,
    )
    gate_evidence_paths = _gate_artifacts(
        tmp_path, materialized, nested, probes.verified_evidence,
    )
    substituted = PostProbeAuthorizationV1(
        nested.policy, nested.public_bindings,
        nested.authorization_raw + b"\n", nested.authorization_sha256,
    )
    with pytest.raises(
        OneRoundCampaignError,
        match="POST_PROBE_AUTHORIZATION_DERIVATION_INVALID",
    ):
        record_mandatory_gates_v1(
            materialized, substituted, repo=repo,
            verified_evidence=probes.verified_evidence,
            verification_key_id=KEY_ID, verification_key=KEY,
            gate_evidence_paths=gate_evidence_paths,
        )
    record_mandatory_gates_v1(
        materialized, nested, repo=repo,
        verified_evidence=probes.verified_evidence,
        verification_key_id=KEY_ID, verification_key=KEY,
        gate_evidence_paths=gate_evidence_paths,
    )
    calls = 0

    async def fake_executor(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return {
            "completion": {"status": "completed"},
            "terminal": {"status": "SUCCESS"},
            "ledger": {"attempts": []},
            "verified_actual_usage": {
                "full_short_provider_request_count": 1,
                "full_short_input_tokens": 1,
                "full_short_output_tokens": 1,
                "campaign_cumulative_provider_request_count": 9,
                "campaign_cumulative_input_tokens": 186734,
                "campaign_cumulative_output_tokens": 9,
                "provider_reported_actual_complete": True,
            },
        }

    dry_source = json.loads(gate_evidence_paths[0].read_text(encoding="utf-8"))
    dry_output_path = Path(dry_source["dry_run_output"]["path"])
    original_dry_output = dry_output_path.read_bytes()
    dry_output_path.write_bytes(original_dry_output + b"tampered")
    with pytest.raises(OneRoundCampaignError, match="RAW_EVIDENCE"):
        await execute_one_full_short_v1(
            materialized, nested, repo=repo, data_dir=tmp_path,
            store_root=tmp_path / "store",
            verified_evidence=probes.verified_evidence,
            verification_key_id=KEY_ID, verification_key=KEY,
            executor=fake_executor,
        )
    assert calls == 0
    dry_output_path.write_bytes(original_dry_output)

    with pytest.raises(OneRoundCampaignError, match="AUTHORITY_DRIFT"):
        await execute_one_full_short_v1(
            materialized, substituted, repo=repo, data_dir=tmp_path,
            store_root=tmp_path / "store",
            verified_evidence=probes.verified_evidence,
            verification_key_id=KEY_ID, verification_key=KEY,
            executor=fake_executor,
        )
    assert calls == 0

    store_root = tmp_path / "store"
    store_root.mkdir(exist_ok=True)
    storage_key = module.domain_sha256(
        "full-short-execution-storage-key-v1", "one-round-test",
    )
    collision_path = store_root / f"{storage_key}.nonce.json"
    collision_path.write_text("{}", encoding="utf-8")
    with pytest.raises(OneRoundCampaignError, match="RUN_ID_COLLISION"):
        await execute_one_full_short_v1(
            materialized, nested, repo=repo, data_dir=tmp_path,
            store_root=store_root,
            verified_evidence=probes.verified_evidence,
            verification_key_id=KEY_ID, verification_key=KEY,
            executor=fake_executor,
        )
    assert calls == 0
    collision_path.unlink()

    result = await execute_one_full_short_v1(
        materialized, nested, repo=repo, data_dir=tmp_path,
        store_root=tmp_path / "store",
        verified_evidence=probes.verified_evidence,
        verification_key_id=KEY_ID, verification_key=KEY,
        executor=fake_executor,
    )
    assert result["completion"]["status"] == "completed"
    with pytest.raises(OneRoundCampaignError, match="NOT_ELIGIBLE_OR_CONSUMED"):
        await execute_one_full_short_v1(
            materialized, nested, repo=repo, data_dir=tmp_path,
            store_root=tmp_path / "store",
            verified_evidence=probes.verified_evidence,
            verification_key_id=KEY_ID, verification_key=KEY,
            executor=fake_executor,
        )
    assert calls == 1


@pytest.mark.asyncio
async def test_full_short_outer_guard_debits_pre_reservation_wall_time_and_terminal_starts_from_reservation(
    tmp_path, monkeypatch,
) -> None:
    materialized, nested, repo, probes = _ready_full_short(
        tmp_path, monkeypatch,
    )
    eligible = module.CampaignJournalV1(
        materialized.evidence_root, materialized.authorization_sha256, KEY,
    ).load()
    campaign_started = eligible["campaign_started_unix_seconds"]

    class FixedClock:
        def __init__(self):
            self.monotonic_values = iter((1_000.0, 1_007.1))

        def time(self):
            return campaign_started + 123

        def monotonic(self):
            return next(self.monotonic_values)

    monkeypatch.setattr(module, "time", FixedClock())
    captured_guard = None

    async def fake_executor(*_args, **kwargs):
        nonlocal captured_guard
        captured_guard = kwargs["outer_campaign_usage_guard"]
        return {
            "completion": {"status": "completed"},
            "terminal": {"status": "SUCCESS"},
            "ledger": {"attempts": []},
            "verified_actual_usage": {
                "full_short_provider_request_count": 1,
                "full_short_input_tokens": 1,
                "full_short_output_tokens": 1,
                "campaign_cumulative_provider_request_count": 9,
                "campaign_cumulative_input_tokens": 186734,
                "campaign_cumulative_output_tokens": 9,
                "provider_reported_actual_complete": True,
            },
        }

    await execute_one_full_short_v1(
        materialized, nested, repo=repo, data_dir=tmp_path,
        store_root=tmp_path / "store",
        verified_evidence=probes.verified_evidence,
        verification_key_id=KEY_ID, verification_key=KEY,
        executor=fake_executor,
    )

    assert captured_guard is not None
    states = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(
            materialized.evidence_root.glob("campaign-state-*.json")
        )
    ]
    reserved = next(
        state for state in states
        if state["phase"] == "FULL_SHORT_RESERVED_NO_RESTART"
    )
    terminal = states[-1]
    assert reserved["usage"]["elapsed_seconds"] == 123
    assert captured_guard["remaining_elapsed_seconds"] == 36_000 - 123
    assert captured_guard["absolute_deadline_unix_seconds"] == (
        campaign_started + 36_000
    )
    assert terminal["phase"] == "TERMINAL_FULL_SHORT_SUCCESS"
    assert terminal["usage"]["elapsed_seconds"] == (
        reserved["usage"]["elapsed_seconds"] + 8
    )


@pytest.mark.asyncio
async def test_full_short_elapsed_expiry_after_reservation_precedes_executor_and_credentials(
    tmp_path, monkeypatch,
) -> None:
    materialized, nested, repo, probes = _ready_full_short(
        tmp_path, monkeypatch,
    )
    eligible = module.CampaignJournalV1(
        materialized.evidence_root, materialized.authorization_sha256, KEY,
    ).load()
    campaign_started = eligible["campaign_started_unix_seconds"]

    class AdvancingClock:
        now = campaign_started + 10

        def time(self):
            return self.now

        @staticmethod
        def monotonic():
            return 1_000.0

    clock = AdvancingClock()
    monkeypatch.setattr(module, "time", clock)
    original_append = module.CampaignJournalV1.append

    def append_then_expire(self, phase, *, usage, evidence):
        state = original_append(
            self, phase, usage=usage, evidence=evidence,
        )
        if phase == "FULL_SHORT_RESERVED_NO_RESTART":
            clock.now = campaign_started + 36_001
        return state

    monkeypatch.setattr(module.CampaignJournalV1, "append", append_then_expire)
    executor_calls = 0
    credential_constructions = 0

    class ForbiddenSecretStore:
        def __init__(self, *_args, **_kwargs):
            nonlocal credential_constructions
            credential_constructions += 1
            raise AssertionError("credential boundary reached")

    async def forbidden_executor(*_args, **kwargs):
        nonlocal executor_calls
        executor_calls += 1
        kwargs["secret_store_factory"]()
        raise AssertionError("executor reached")

    monkeypatch.setattr(module, "KeyringSecretStore", ForbiddenSecretStore)
    with pytest.raises(
        OneRoundCampaignError, match="CAMPAIGN_ELAPSED_CAP_EXHAUSTED",
    ):
        await execute_one_full_short_v1(
            materialized, nested, repo=repo, data_dir=tmp_path,
            store_root=tmp_path / "store",
            verified_evidence=probes.verified_evidence,
            verification_key_id=KEY_ID, verification_key=KEY,
            executor=forbidden_executor,
        )

    assert executor_calls == 0
    assert credential_constructions == 0
    terminal = module.CampaignJournalV1(
        materialized.evidence_root, materialized.authorization_sha256, KEY,
    ).load()
    assert terminal["phase"] == "FULL_SHORT_RESERVED_NO_RESTART"
    assert terminal["usage"]["elapsed_seconds"] == 10


def test_gate_sources_reject_duplicate_review_identity(
    tmp_path, monkeypatch,
) -> None:
    materialized, repo, fixtures, db, policy, public, actual = (
        _materialized(tmp_path, monkeypatch)
    )
    probes = run_probe_phase_v1(
        materialized, repo=repo, fixtures=fixtures, db=db,
        store_root=tmp_path / "store",
        verification_key_id=KEY_ID, verification_key=KEY,
        runner=_offline_runner,
    )
    post_public, post_actual = _post_probe_public(
        public, actual, probes.verified_evidence,
    )
    monkeypatch.setattr(
        module, "collect_live_bindings", lambda **_kwargs: (post_actual, post_public),
    )
    nested = derive_post_probe_authorization_v1(
        materialized, repo=repo, data_dir=tmp_path,
        store_root=tmp_path / "store", template_policy=policy,
        verified_evidence=probes.verified_evidence,
        verification_key_id=KEY_ID, verification_key=KEY,
    )
    paths = _gate_artifacts(
        tmp_path, materialized, nested, probes.verified_evidence,
        duplicate_role=True,
    )
    with pytest.raises(OneRoundCampaignError, match="MANDATORY_REVIEW"):
        record_mandatory_gates_v1(
            materialized, nested, repo=repo,
            verified_evidence=probes.verified_evidence,
            verification_key_id=KEY_ID, verification_key=KEY,
            gate_evidence_paths=paths,
        )


def test_gate_sources_reject_plain_text_before_receipt_derivation(
    tmp_path, monkeypatch,
) -> None:
    materialized, repo, fixtures, db, policy, public, actual = (
        _materialized(tmp_path, monkeypatch)
    )
    probes = run_probe_phase_v1(
        materialized, repo=repo, fixtures=fixtures, db=db,
        store_root=tmp_path / "store",
        verification_key_id=KEY_ID, verification_key=KEY,
        runner=_offline_runner,
    )
    post_public, post_actual = _post_probe_public(
        public, actual, probes.verified_evidence,
    )
    monkeypatch.setattr(
        module, "collect_live_bindings", lambda **_kwargs: (post_actual, post_public),
    )
    nested = derive_post_probe_authorization_v1(
        materialized, repo=repo, data_dir=tmp_path,
        store_root=tmp_path / "store", template_policy=policy,
        verified_evidence=probes.verified_evidence,
        verification_key_id=KEY_ID, verification_key=KEY,
    )
    paths = list(_gate_artifacts(
        tmp_path, materialized, nested, probes.verified_evidence,
    ))
    paths[0].write_text("PASS", encoding="utf-8")
    with pytest.raises(OneRoundCampaignError, match="NOT_CANONICAL_JSON"):
        record_mandatory_gates_v1(
            materialized, nested, repo=repo,
            verified_evidence=probes.verified_evidence,
            verification_key_id=KEY_ID, verification_key=KEY,
            gate_evidence_paths=tuple(paths),
        )


def test_gate_sources_recompute_raw_files_and_reject_forged_summaries(
    tmp_path, monkeypatch,
) -> None:
    materialized, repo, fixtures, db, policy, public, actual = (
        _materialized(tmp_path, monkeypatch)
    )
    probes = run_probe_phase_v1(
        materialized, repo=repo, fixtures=fixtures, db=db,
        store_root=tmp_path / "store",
        verification_key_id=KEY_ID, verification_key=KEY,
        runner=_offline_runner,
    )
    post_public, post_actual = _post_probe_public(
        public, actual, probes.verified_evidence,
    )
    monkeypatch.setattr(
        module, "collect_live_bindings", lambda **_kwargs: (post_actual, post_public),
    )
    nested = derive_post_probe_authorization_v1(
        materialized, repo=repo, data_dir=tmp_path,
        store_root=tmp_path / "store", template_policy=policy,
        verified_evidence=probes.verified_evidence,
        verification_key_id=KEY_ID, verification_key=KEY,
    )

    paths = list(_gate_artifacts(
        tmp_path, materialized, nested, probes.verified_evidence,
    ))
    forged = json.loads(paths[0].read_text(encoding="utf-8"))
    forged["status"] = "PASS"
    paths[0].write_bytes(module.canonical_json_bytes(forged))
    with pytest.raises(OneRoundCampaignError, match="MANDATORY_DRY_RUN"):
        record_mandatory_gates_v1(
            materialized, nested, repo=repo,
            verified_evidence=probes.verified_evidence,
            verification_key_id=KEY_ID, verification_key=KEY,
            gate_evidence_paths=tuple(paths),
        )


def test_dry_gate_rejects_semantically_stale_maintenance_and_missing_stage_artifacts(
    tmp_path, monkeypatch,
) -> None:
    materialized, repo, fixtures, db, policy, public, actual = (
        _materialized(tmp_path, monkeypatch)
    )
    probes = run_probe_phase_v1(
        materialized, repo=repo, fixtures=fixtures, db=db,
        store_root=tmp_path / "store",
        verification_key_id=KEY_ID, verification_key=KEY,
        runner=_offline_runner,
    )
    post_public, post_actual = _post_probe_public(
        public, actual, probes.verified_evidence,
    )
    monkeypatch.setattr(
        module, "collect_live_bindings",
        lambda **_kwargs: (post_actual, post_public),
    )
    nested = derive_post_probe_authorization_v1(
        materialized, repo=repo, data_dir=tmp_path,
        store_root=tmp_path / "store", template_policy=policy,
        verified_evidence=probes.verified_evidence,
        verification_key_id=KEY_ID, verification_key=KEY,
    )

    def rewrite_reference(reference, value):
        raw = module.canonical_json_bytes(value)
        Path(reference["path"]).write_bytes(raw)
        reference["sha256"] = hashlib.sha256(raw).hexdigest()

    def stale_inventory(manifest):
        reference = manifest["receipts"]["maintenance_receipts"][0]["evidence"]
        inventory = MaintenanceProposalInventoryV1.model_validate_json(
            Path(reference["path"]).read_bytes()
        )
        invalid = make_maintenance_inventory(
            source_mode=inventory.source_mode,
            source_artifact_hash="0" * 64,
            base_authority_revision=inventory.base_authority_revision,
            base_authority_hash=inventory.base_authority_hash,
            units=inventory.units,
        )
        rewrite_reference(
            reference, invalid.model_dump(mode="json", by_alias=True),
        )

    def coverage_gap(manifest):
        reference = manifest["receipts"]["maintenance_receipts"][0]["evidence"]
        inventory = MaintenanceProposalInventoryV1.model_validate_json(
            Path(reference["path"]).read_bytes()
        )
        invalid = make_maintenance_inventory(
            source_mode=inventory.source_mode,
            source_artifact_hash=inventory.source_artifact_hash,
            base_authority_revision=inventory.base_authority_revision,
            base_authority_hash=inventory.base_authority_hash,
            units=inventory.units, complete=False,
            coverage_gaps=("missing-owned-source",),
        )
        rewrite_reference(
            reference, invalid.model_dump(mode="json", by_alias=True),
        )

    def wrong_model_role(manifest):
        rewrite_reference(
            manifest["receipts"]["maintenance_model_receipt"],
            {"model": {"role": "draft"}},
        )

    def empty_maintenance_output(manifest):
        # A syntactically JSON model output with no business-complete v2
        # authority must not inherit legitimacy from the inventory receipt.
        rewrite_reference(
            manifest["receipts"]["maintenance_output"],
            {"facts": [], "state": {}},
        )

    def coherent_synthetic_authorization(manifest):
        # Rebuild a self-consistent authorization triple under a different
        # run identity.  Its own policy seal and rendered bytes are valid, but
        # it is not the fixed dry execution or the durable chain being gated.
        receipts = manifest["receipts"]
        policy_ref = receipts["authorization_policy"]
        public_ref = receipts["authorization_public_bindings"]
        policy = json.loads(Path(policy_ref["path"]).read_bytes())
        public = json.loads(Path(public_ref["path"]).read_bytes())
        policy["run_id"] = "synthetic-private-dry-run"
        policy.pop("policy_sha256")
        policy["policy_sha256"] = module.domain_sha256(
            "novel-flywheel-full-short-execution-policy-v1", policy,
        )
        public["run_id"] = policy["run_id"]
        authorization_raw = module.render_full_short_canonical_authorization_v1(
            policy=policy, public_bindings=public,
        )
        rewrite_reference(policy_ref, policy)
        rewrite_reference(public_ref, public)
        authorization_ref = receipts["canonical_authorization"]
        Path(authorization_ref["path"]).write_bytes(authorization_raw)
        authorization_ref["sha256"] = hashlib.sha256(
            authorization_raw
        ).hexdigest()

    def missing_stage_artifact(manifest):
        manifest["receipts"]["stage_artifacts"].pop("quality-report.json")

    def coherent_causal_forgery(manifest):
        stages = manifest["receipts"]["stage_artifacts"]
        causal_ref = stages["short-causal-chain.json"]
        causal = json.loads(Path(causal_ref["path"]).read_bytes())
        causal["covered_event_ids"] = []
        rewrite_reference(causal_ref, causal)
        execution_ref = stages["short-execution-index.json"]
        execution = json.loads(Path(execution_ref["path"]).read_bytes())
        execution["causal_chain_sha256"] = module._json_sha256(causal)
        rewrite_reference(execution_ref, execution)
        manifest["authority_bindings"][
            "required_stage_artifacts_sha256"
        ] = module._json_sha256([
            {"name": name, "sha256": reference["sha256"]}
            for name, reference in sorted(stages.items())
        ])

    def coherent_base_authority_forgery(manifest):
        receipts = manifest["receipts"]
        base_ref = receipts["base_story_state"]
        base = json.loads(Path(base_ref["path"]).read_bytes())
        base["data"]["confirmed_facts"] = [{
            "key": "forged.authority", "value": "recomputed",
        }]
        forged_base_sha = canonical_json_sha256(base["data"])
        base["authority_sha256"] = forged_base_sha
        rewrite_reference(base_ref, base)
        forged_source_sha = module.WorkflowService._text_hash(json.dumps(
            module.WorkflowService._short_maintenance_state_authority(
                base["data"]
            ),
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ))
        authority = manifest["maintenance_authority"]
        authority["base_story_state_sha256"] = forged_base_sha
        authority["maintenance_source_state_sha256"] = forged_source_sha

        inventory_ref = receipts["maintenance_receipts"][0]["evidence"]
        inventory = MaintenanceProposalInventoryV1.model_validate_json(
            Path(inventory_ref["path"]).read_bytes()
        )
        forged_inventory = make_maintenance_inventory(
            source_mode=inventory.source_mode,
            source_artifact_hash=inventory.source_artifact_hash,
            base_authority_revision=inventory.base_authority_revision,
            base_authority_hash=forged_base_sha,
            units=inventory.units,
        )
        rewrite_reference(
            inventory_ref,
            forged_inventory.model_dump(mode="json", by_alias=True),
        )
        maintenance_sha = module.domain_sha256(
            "novel-flywheel-short-maintenance-receipts-v1",
            [{
                "kind": "MaintenanceProposalInventoryV1",
                "sha256": inventory_ref["sha256"],
            }],
        )

        ready_ref = receipts["ready"]
        ready = json.loads(Path(ready_ref["path"]).read_bytes())
        ready["base_authority_hash"] = forged_base_sha
        ready.pop("receipt_hash")
        ready["receipt_hash"] = canonical_sha256(
            "ShortCanonicalCommitReceiptV1", ready,
        )
        rewrite_reference(ready_ref, ready)

        journal_ref = receipts["project_mutation_journal"]
        journal = json.loads(Path(journal_ref["path"]).read_bytes())
        journal["source_authority_sha256"] = forged_base_sha
        journal["post_commit_gate"]["receipt_sha256"] = ready_ref["sha256"]
        rewrite_reference(journal_ref, journal)

        terminal_ref = receipts["terminal_verification"]
        terminal = json.loads(Path(terminal_ref["path"]).read_bytes())
        terminal["maintenance"]["artifact_receipt_sha256"] = maintenance_sha
        terminal["maintenance"]["project_mutation_journal_sha256"] = (
            journal_ref["sha256"]
        )
        terminal.pop("verification_receipt_sha256")
        terminal["verification_receipt_sha256"] = module.domain_sha256(
            "novel-flywheel-short-completion-verification-v1", terminal,
        )
        rewrite_reference(terminal_ref, terminal)

        completion_ref = receipts["completion"]
        completion = json.loads(Path(completion_ref["path"]).read_bytes())
        completion["final_bindings"]["terminal_verification_sha256"] = (
            terminal["verification_receipt_sha256"]
        )
        completion.pop("completion_receipt_sha256")
        completion["completion_receipt_sha256"] = module.domain_sha256(
            "novel-flywheel-full-short-completion-receipt-v1", completion,
        )
        rewrite_reference(completion_ref, completion)

        bindings = manifest["authority_bindings"]
        bindings["completion_receipt_sha256"] = completion[
            "completion_receipt_sha256"
        ]
        bindings["terminal_verification_sha256"] = terminal[
            "verification_receipt_sha256"
        ]
        bindings["ready_receipt_sha256"] = ready_ref["sha256"]
        bindings["project_mutation_journal_sha256"] = journal_ref["sha256"]
        bindings["maintenance_artifact_receipt_sha256"] = maintenance_sha

    def substituted_project_workload(manifest):
        reference = manifest["receipts"]["project"]
        project = json.loads(Path(reference["path"]).read_bytes())
        project["target_words"] = 20_000
        rewrite_reference(reference, project)
        manifest["authority_bindings"]["project_json_sha256"] = reference[
            "sha256"
        ]

    def substituted_constraints(manifest):
        reference = manifest["receipts"]["constraints"]
        raw = b"substituted constraints"
        Path(reference["path"]).write_bytes(raw)
        reference["sha256"] = hashlib.sha256(raw).hexdigest()
        manifest["authority_bindings"]["constraints_sha256"] = reference[
            "sha256"
        ]

    def rehashed_unbound_quality_checkpoint(manifest):
        reference = manifest["receipts"]["quality_checkpoint"]
        checkpoint = json.loads(Path(reference["path"]).read_bytes())
        checkpoint["score"] = 91
        rewrite_reference(reference, checkpoint)
        manifest["authority_bindings"]["quality_checkpoint_sha256"] = (
            reference["sha256"]
        )

    def coherent_invalid_terminal_verdict(manifest):
        receipts = manifest["receipts"]
        stages = receipts["stage_artifacts"]
        report_ref = stages["quality-report.json"]
        report = json.loads(Path(report_ref["path"]).read_bytes())
        report["terminal_review"]["decision"] = "forged-pass"
        rewrite_reference(report_ref, report)

        checkpoint_ref = receipts["quality_checkpoint"]
        checkpoint = json.loads(Path(checkpoint_ref["path"]).read_bytes())
        checkpoint["review"] = report["terminal_review"]
        rewrite_reference(checkpoint_ref, checkpoint)

        terminal_ref = receipts["terminal_verification"]
        terminal = json.loads(Path(terminal_ref["path"]).read_bytes())
        terminal["final_checkpoint"]["checkpoint_sha256"] = checkpoint_ref[
            "sha256"
        ]
        terminal.pop("verification_receipt_sha256")
        terminal["verification_receipt_sha256"] = module.domain_sha256(
            "novel-flywheel-short-completion-verification-v1", terminal,
        )
        rewrite_reference(terminal_ref, terminal)

        completion_ref = receipts["completion"]
        completion = json.loads(Path(completion_ref["path"]).read_bytes())
        completion["final_bindings"]["quality_checkpoint_sha256"] = (
            checkpoint_ref["sha256"]
        )
        completion["final_bindings"]["terminal_verification_sha256"] = (
            terminal["verification_receipt_sha256"]
        )
        completion.pop("completion_receipt_sha256")
        completion["completion_receipt_sha256"] = module.domain_sha256(
            "novel-flywheel-full-short-completion-receipt-v1", completion,
        )
        rewrite_reference(completion_ref, completion)

        bindings = manifest["authority_bindings"]
        bindings["completion_receipt_sha256"] = completion[
            "completion_receipt_sha256"
        ]
        bindings["terminal_verification_sha256"] = terminal[
            "verification_receipt_sha256"
        ]
        bindings["quality_checkpoint_sha256"] = checkpoint_ref["sha256"]
        bindings["required_stage_artifacts_sha256"] = module._json_sha256([
            {"name": name, "sha256": reference["sha256"]}
            for name, reference in sorted(stages.items())
        ])

    splice_paths = _gate_artifacts(
        tmp_path, materialized, nested, probes.verified_evidence,
    )
    splice_source = json.loads(splice_paths[0].read_bytes())
    splice_manifest = json.loads(Path(
        splice_source["isolated_evidence_manifest"]["path"]
    ).read_bytes())

    def coherently_spliced_durable_receipt(manifest):
        # The replacement is a genuinely sealed completion from a separate
        # production durable store.  Hashes remain correct, but cross-store
        # provenance must reject the splice.
        manifest["receipts"]["control_store"]["completion"] = copy.deepcopy(
            splice_manifest["receipts"]["control_store"]["completion"]
        )

    length_paths = _gate_artifacts(
        tmp_path, materialized, nested, probes.verified_evidence,
    )
    length_source = json.loads(length_paths[0].read_bytes())
    length_manifest = json.loads(Path(
        length_source["isolated_evidence_manifest"]["path"]
    ).read_bytes())
    length_receipts = length_manifest["receipts"]
    length_stages = {
        name: Path(reference["path"]).read_bytes()
        for name, reference in length_receipts["stage_artifacts"].items()
    }
    short_for_target_project = json.loads(Path(
        length_receipts["project"]["path"]
    ).read_bytes())
    short_for_target_project["target_words"] = 1_000_000
    with pytest.raises(OneRoundCampaignError, match="MANDATORY_DRY_RUN"):
        module._validate_full_short_stage_artifacts_v1(
            artifacts=length_stages,
            base_story_state=json.loads(Path(
                length_receipts["base_story_state"]["path"]
            ).read_bytes()),
            project=short_for_target_project,
            final_manuscript=Path(
                length_receipts["final_artifact"]["path"]
            ).read_text(encoding="utf-8"),
            chapter_bytes=Path(
                length_receipts["chapter"]["path"]
            ).read_bytes(),
            narrative_integrity=json.loads(Path(
                length_receipts["narrative_integrity"]["path"]
            ).read_bytes()),
        )

    for mutate in (
        stale_inventory, coverage_gap, wrong_model_role,
        empty_maintenance_output, coherent_synthetic_authorization,
        coherently_spliced_durable_receipt,
        missing_stage_artifact, coherent_causal_forgery,
        coherent_base_authority_forgery, substituted_project_workload,
        substituted_constraints, rehashed_unbound_quality_checkpoint,
        coherent_invalid_terminal_verdict,
    ):
        paths = _gate_artifacts(
            tmp_path, materialized, nested, probes.verified_evidence,
        )
        _rewrite_dry_manifest_source(paths[0], mutate)
        with pytest.raises(OneRoundCampaignError, match="MANDATORY_DRY_RUN"):
            record_mandatory_gates_v1(
                materialized, nested, repo=repo,
                verified_evidence=probes.verified_evidence,
                verification_key_id=KEY_ID, verification_key=KEY,
                gate_evidence_paths=paths,
            )

    paths = list(_gate_artifacts(
        tmp_path, materialized, nested, probes.verified_evidence,
    ))
    dry_source = json.loads(paths[0].read_bytes())
    dry_reference = dry_source["dry_run_output"]
    dry_output = json.loads(Path(dry_reference["path"]).read_bytes())
    dry_output["runtime_authority_sha256"] = "f" * 64
    rewrite_reference(dry_reference, dry_output)
    paths[0].write_bytes(module.canonical_json_bytes(dry_source))
    with pytest.raises(OneRoundCampaignError, match="MANDATORY_DRY_RUN"):
        record_mandatory_gates_v1(
            materialized, nested, repo=repo,
            verified_evidence=probes.verified_evidence,
            verification_key_id=KEY_ID, verification_key=KEY,
            gate_evidence_paths=tuple(paths),
        )

    paths = list(_gate_artifacts(
        tmp_path, materialized, nested, probes.verified_evidence,
    ))
    dry_source = json.loads(paths[0].read_text(encoding="utf-8"))
    dry_manifest_ref = dry_source["isolated_evidence_manifest"]
    dry_manifest = json.loads(Path(dry_manifest_ref["path"]).read_text(encoding="utf-8"))
    final_path = Path(dry_manifest["receipts"]["final_artifact"]["path"])
    final_path.write_bytes(final_path.read_bytes() + b"tampered")
    with pytest.raises(OneRoundCampaignError, match="RAW_EVIDENCE"):
        record_mandatory_gates_v1(
            materialized, nested, repo=repo,
            verified_evidence=probes.verified_evidence,
            verification_key_id=KEY_ID, verification_key=KEY,
            gate_evidence_paths=tuple(paths),
        )

    paths = list(_gate_artifacts(
        tmp_path, materialized, nested, probes.verified_evidence,
    ))
    size_source = json.loads(paths[1].read_text(encoding="utf-8"))
    size_manifest = json.loads(Path(
        size_source["envelope_manifest"]["path"]
    ).read_text(encoding="utf-8"))
    payload_path = Path(size_manifest["run_records"][0][
        "provider_wire_envelopes"
    ][0]["payload_evidence"]["path"])
    payload_path.write_bytes(payload_path.read_bytes() + b"tampered")
    with pytest.raises(OneRoundCampaignError, match="RAW_EVIDENCE"):
        record_mandatory_gates_v1(
            materialized, nested, repo=repo,
            verified_evidence=probes.verified_evidence,
            verification_key_id=KEY_ID, verification_key=KEY,
            gate_evidence_paths=tuple(paths),
        )

    paths = list(_gate_artifacts(
        tmp_path, materialized, nested, probes.verified_evidence,
    ))
    (repo / "src/review-core.py").write_text("CORE = False\n", encoding="utf-8")
    with pytest.raises(OneRoundCampaignError, match="MANDATORY_"):
        record_mandatory_gates_v1(
            materialized, nested, repo=repo,
            verified_evidence=probes.verified_evidence,
            verification_key_id=KEY_ID, verification_key=KEY,
            gate_evidence_paths=tuple(paths),
        )

    paths = list(_gate_artifacts(
        tmp_path, materialized, nested, probes.verified_evidence,
    ))
    (repo / "tests/review-test.py").write_text("raise RuntimeError\n", encoding="utf-8")
    with pytest.raises(OneRoundCampaignError, match="REVIEW_GATE"):
        record_mandatory_gates_v1(
            materialized, nested, repo=repo,
            verified_evidence=probes.verified_evidence,
            verification_key_id=KEY_ID, verification_key=KEY,
            gate_evidence_paths=tuple(paths),
        )
