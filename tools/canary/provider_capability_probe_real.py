"""Single-use signed execution closure for the R1-PTR4 capability probe.

The module is inert on import.  Materialization and validate-only never read a
credential, construct a Provider client, use the network, or call a model.
Only ``execute`` crosses the separately authorized paid boundary, exactly once.
Raw prompts, story material, tool arguments, Provider content, credentials, and
headers are kept in memory only and are never written or printed.
"""

from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time
from typing import Any, Mapping

from novel_flywheel.app import create_app
from novel_flywheel.contract_runtime import _protocol_regeneration_system
from novel_flywheel.context_policy import estimate_input_tokens
from novel_flywheel.db import Database
from novel_flywheel.domain.models import Message, ModelRequest
from novel_flywheel.model_output import parse_json_object
from novel_flywheel.outlines import canon_profile, narrative_outline_events
from novel_flywheel.planning_semantics import (
    PlanningSemanticDraftV2,
    merge_planning_semantic_event_packets_v2,
    normalize_planning_semantic_v2_payload,
)
from novel_flywheel.providers.registry import ProviderRegistry
from novel_flywheel.reference_library import ReferenceLibrary
from novel_flywheel.runtime_fingerprint_build import domain_sha256
from novel_flywheel.secrets import KeyringSecretStore
from novel_flywheel.models import ModelResult

from .approval_profiles import SHORT_COMPLETION_PROFILE_ID, approval_profile
from .artifact_hash import file_sha256, live_parity_manifest, parity_equal
from .descriptors import production_route_identity
from .dry_run import C0AFakeWorkflowService
from .environment import c0a_environment
from .provider_capability_probe_contract import (
    ProviderContentBlockMetadataV1,
    build_provider_capability_probe_definition_v1,
    build_provider_capability_probe_fixture_v1,
    build_provider_capability_probe_observation_v1,
)
from .provider_capability_probe_materialization import (
    EXPECTED_PTR4_CANONICAL_SHA256,
    EXPECTED_PTR4_V1_CANONICAL_SHA256,
    PARENT_PTR4_MANIFEST,
    PARENT_PTR4_V1_MANIFEST,
    verify_sha_manifest_exact,
)
from .provider_matrix import production_price_catalog


PROFILE_ID = "r1_ptr4_provider_capability_probe_1"
COHORT_ID = "r1-ptr4-probe-20260820t110721z-001"
PLAN_SHA256 = "6bc5672575098fcd94fe873de4e5fb880c5e396d76f0c49b87b406c1aa899749"
CANDIDATE_SHA256 = "f8e25a05cf8d8f8fa35e4d14f81f6ac4c24d523bedd31de5e39fec4d79677bf3"
PATCH_TEMPLATE_SHA256 = "27167c4eea1c401bd63ecac1d8843e731c479bfa96a3c49327aec31e4d6dd716"
DISABLED_RECEIPT_SHA256 = "8d83290ae0558a3d24705d8e72dd9b425d052ff3a2cd33acc86133e808c481a6"
DEFINITION_SHA256 = "6f201a3687d46d7be83f7c9797b03b26abdd346cc897f0f1ef87f0ab57ae5aee"
FIXTURE_SHA256 = "22ac37e6494de79f542596cd16d5c14b8b25229af5cc1f451957e101b1c87e64"
OBSERVER_SHA256 = "d88652767f2d5fe72fce529cdc51c51e7897daa9b16fd869092aa20b30d7dfa3"
TARGET_SHA256 = "851b447afba31d2296ebafc223ea4189464920e332693a5a03d5cf0b821675f0"
PROVIDER_SHA256 = "98190f8a4627638591d90646f663d859e5cb8b8fa138ef3d250e43317c1705a6"
MODEL_SHA256 = "fa876d1792c79f4cfa4209a3384a407b6cd48f5bbdf49a920d74cdfca9bf0998"
SYSTEM_SHA256 = "d6ad1c9d2d36a9f9f8703fc89a46f004d569cce9085a50c7d595db4b9330f2aa"
USER_SHA256 = "2d339af183abe5980945cc3c2d0ba5abaa82f7b2c43500bbafb53653c60667ed"
NOT_BEFORE = "2026-08-20T11:22:21Z"
NOT_AFTER = "2026-08-22T11:22:21Z"
MAX_INPUT_TOKENS = 128_000
MAX_OUTPUT_TOKENS = 8_798
MAX_USD_MICROUNITS = 5_000_000
MAX_CNY_MICROUNITS = 10_000_000
MAX_ELAPSED_SECONDS = 1_800
FINAL_MANIFEST_CANONICAL_SHA256 = (
    "f94213551ad6a065686c1681a4cd3671882f9973e5a0daf0c01aafd2f75bdd8f"
)


class ProviderCapabilityProbeRealError(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class _CapturedRequest(BaseException):
    pass


class _NoCredentialStore:
    def __init__(self) -> None:
        self.lookup_count = 0

    def get(self, _provider_id: str) -> str | None:
        self.lookup_count += 1
        raise ProviderCapabilityProbeRealError(
            "credential_lookup_forbidden_before_signed_validate_exact"
        )

    def set(self, _provider_id: str, _value: str) -> None:
        raise ProviderCapabilityProbeRealError("credential_mutation_forbidden")

    def delete(self, _provider_id: str) -> None:
        raise ProviderCapabilityProbeRealError("credential_mutation_forbidden")


class _CaptureGateway:
    def __init__(self) -> None:
        self.capture: dict[str, Any] | None = None
        self.call_count = 0

    def has_configured_fallback(self, _role: str) -> bool:
        return True

    async def complete_route(
        self, route: str, role: str, system: str, user: str, **kwargs: Any,
    ) -> Any:
        self.call_count += 1
        # The historical target is the first nested packet request.  Four
        # deterministic offline output-limit results exercise only the local
        # contract topology needed to select that nested packet; they never
        # create a Provider client or external action.  No response content is
        # guessed or used as narrative authority.
        if self.call_count <= 4:
            budget = int(kwargs.get("max_output_tokens") or 0)
            return ModelResult("", {
                "finish_reason": "max_tokens",
                "input_tokens": 0,
                "output_tokens": budget,
                "requested_max_output_tokens": budget,
                "execution_mode": "plain",
            })
        self.capture = {
            "route": route, "role": role, "system": system, "user": user,
            "max_output_tokens": kwargs.get("max_output_tokens"),
        }
        raise _CapturedRequest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ProviderCapabilityProbeRealError("document_not_object")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            dict(value), ensure_ascii=False, sort_keys=True, indent=2,
            allow_nan=False,
        ) + "\n",
        encoding="utf-8",
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z",
    )


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
        timezone.utc,
    )


def _require(condition: bool, reason_code: str) -> None:
    if not condition:
        raise ProviderCapabilityProbeRealError(reason_code)


def _sealed(domain: str, body: Mapping[str, Any], field: str) -> dict[str, Any]:
    value = dict(body)
    value[field] = domain_sha256(domain, value)
    return value


def _document_digest(domain: str, value: Mapping[str, Any], field: str) -> str:
    body = dict(value)
    body.pop(field, None)
    return domain_sha256(domain, body)


def packet_paths(packet_root: Path) -> dict[str, Path]:
    material = packet_root / "materialization-v1"
    return {
        "plan": material / "provider-capability-probe-plan-v1.json",
        "candidate": material / "provider-capability-probe-final-approval-candidate-v1.json",
        "template": material / "provider-capability-probe-authorization-patch-template-v1.json",
        "disabled_receipt": material / "provider-capability-probe-validate-only-receipt-v1.json",
        "final_manifest": packet_root / "r1-ptr4-probe-mat-final-sha256-manifest-v1.json",
        "packet_ledger": packet_root / "ledger" / "provider-capability-probe-approval-ledger-v1.json",
        "canary_root": packet_root / "canary-root" / "provider-capability-probe-canary-root-identity-v1.json",
    }


def verify_fresh_packet_exact(repo_root: Path, packet_root: Path) -> dict[str, Any]:
    paths = packet_paths(packet_root)
    verify_sha_manifest_exact(
        repo_root, paths["final_manifest"].relative_to(repo_root),
        FINAL_MANIFEST_CANONICAL_SHA256,
    )
    verify_sha_manifest_exact(
        repo_root, PARENT_PTR4_MANIFEST, EXPECTED_PTR4_CANONICAL_SHA256,
    )
    verify_sha_manifest_exact(
        repo_root, PARENT_PTR4_V1_MANIFEST, EXPECTED_PTR4_V1_CANONICAL_SHA256,
    )
    plan = _read_json(paths["plan"])
    candidate = _read_json(paths["candidate"])
    template = _read_json(paths["template"])
    disabled = _read_json(paths["disabled_receipt"])
    ledger = _read_json(paths["packet_ledger"])
    root = _read_json(paths["canary_root"])
    _require(plan.get("plan_sha256") == PLAN_SHA256, "plan_sha256_mismatch")
    _require(
        candidate.get("approval_candidate_sha256") == CANDIDATE_SHA256,
        "candidate_sha256_mismatch",
    )
    _require(
        template.get("authorization_patch_template_sha256")
        == PATCH_TEMPLATE_SHA256,
        "patch_template_sha256_mismatch",
    )
    _require(
        disabled.get("validate_only_receipt_sha256")
        == DISABLED_RECEIPT_SHA256
        and disabled.get("overall_status") == "exact",
        "disabled_validate_only_not_exact",
    )
    _require(
        candidate.get("execution_authorized") is False
        and candidate.get("usage_status") == "unused"
        and candidate.get("reservation_status") == "unreserved",
        "candidate_not_fresh_disabled_unused",
    )
    _require(
        ledger.get("entry_count") == 0
        and ledger.get("usage_status") == "unused"
        and ledger.get("reservation_status") == "unreserved",
        "packet_ledger_not_unused",
    )
    _require(
        root.get("entry_count") == 0 and root.get("status") == "unused",
        "packet_canary_root_not_unused",
    )
    budget = candidate.get("approved_budget") or {}
    expected_budget = {
        "maximum_runs": 1,
        "expected_model_calls": 1,
        "maximum_total_model_calls": 1,
        "maximum_input_tokens": MAX_INPUT_TOKENS,
        "maximum_output_tokens": MAX_OUTPUT_TOKENS,
        "maximum_output_tokens_per_call": MAX_OUTPUT_TOKENS,
        "maximum_usd_cost": 5,
        "maximum_cny_cost": 10,
        "maximum_elapsed_seconds": MAX_ELAPSED_SECONDS,
        "first_terminal_stop": True,
        "resume_after_terminal": False,
        "second_run_allowed": False,
    }
    _require(
        all(budget.get(key) == value for key, value in expected_budget.items()),
        "approved_budget_mismatch",
    )
    _require(
        plan.get("profile_id") == PROFILE_ID
        and plan.get("single_use_cohort_id") == COHORT_ID
        and plan.get("probe_definition_sha256") == DEFINITION_SHA256
        and plan.get("probe_fixture_sha256") == FIXTURE_SHA256
        and plan.get("observer_schema_sha256") == OBSERVER_SHA256
        and plan.get("target_boundary_identity_sha256") == TARGET_SHA256,
        "packet_scope_binding_mismatch",
    )
    return {
        "plan": plan, "candidate": candidate, "template": template,
        "disabled_receipt": disabled, "packet_ledger": ledger,
        "canary_root": root,
    }


def _rewrite_cloned_project_paths(clone_root: Path) -> tuple[str, Path]:
    projects = [path for path in (clone_root / "projects").iterdir() if path.is_dir()]
    _require(len(projects) == 1, "reassembly_project_not_unique")
    project_path = projects[0].resolve()
    metadata_path = project_path / "project.json"
    metadata = _read_json(metadata_path)
    project_id = str(metadata.get("id") or "")
    _require(bool(project_id), "reassembly_project_id_missing")
    # Keep the archived metadata byte-for-byte.  ``root_constraints`` was part
    # of the original deterministic brief and therefore contributes to the
    # sealed Boundary 12 request hash.  Only the cloned SQLite storage pointer
    # is relocated; absolute paths are never emitted by the resulting receipt.
    database_path = clone_root / "db" / "app.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE projects SET path = ? WHERE id = ?",
            (str(project_path), project_id),
        )
        connection.commit()
    return project_id, project_path


def _build_brief(project: Any, state: Mapping[str, Any], formal_events: list[dict]) -> str:
    target_words = int(project.metadata["target_words"])
    segment_count = C0AFakeWorkflowService._short_segment_count(target_words)
    return json.dumps({
        **project.metadata,
        "formal_story_facts": canon_profile(project, dict(state)),
        "formal_outline_events": narrative_outline_events(formal_events),
        "generation_contract": {
            "target_total_words": target_words,
            "segment_count": segment_count,
            "require_segment_map": segment_count > 1,
            "segment_heading_format": (
                f"### 第 1 段：标题，依次编号到 ### 第 {segment_count} 段：标题"
            ),
            "segment_block_fields": ([
                "事件ID：认领正式大纲事件表中的一个或多个 ID；连续分段可共同完成同一事件",
                "大纲依据：对应的正式大纲事件名称",
                "段首承接：上一段留下的人物位置、动作、关系和已知信息",
                "本段事件：本段唯一负责的事件",
                "段末交接：留给下一段的人物位置、动作、关系和已知信息",
            ] if segment_count > 1 else []),
        },
        "short_causal_chain_contract": {
            "purpose": "append whole-story causal-chain JSON without replacing the outline",
            "start_marker": "SHORT_CAUSAL_CHAIN_JSON_START",
            "end_marker": "SHORT_CAUSAL_CHAIN_JSON_END",
            "fields": [
                "core_goal", "opening", "cycles", "accidents", "reversal",
                "ending", "question_chain", "relationship_arc",
            ],
            "cycle_shape": [
                "obstacle", "effort", "result", "state_change", "escalation",
                "next_question",
            ],
            "opening_shape": [
                "pressure", "anomaly", "reader_question", "future_promise",
            ],
            "ending_shape": ["surface_goal", "inner_goal", "cost"],
        },
    }, ensure_ascii=False, indent=2)


async def _capture_base_request(clone_root: Path) -> dict[str, Any]:
    project_id, project_path = _rewrite_cloned_project_paths(clone_root)
    secrets = _NoCredentialStore()
    db = Database(clone_root / "db" / "app.db")
    references = ReferenceLibrary(db, clone_root / "references")
    profile = approval_profile(SHORT_COMPLETION_PROFILE_ID)
    with c0a_environment(clone_root, feature_flags=profile.required_flags()):
        app = create_app(
            db, secrets, skill_roots=[clone_root / "skills"],
            workspace_root=clone_root / "projects",
            root_constraints=[clone_root / "constraints-source.md"],
            reference_library=references,
        )
        gateway = _CaptureGateway()
        service = C0AFakeWorkflowService(
            db, app.state.projects, gateway, app.state.skill_gate,
            clone_root / "crewai", local_nlp=app.state.local_nlp,
            references=app.state.references,
        )
        project = app.state.projects.get(project_id)
        state = service.story_states.get(project_id)
        _require(state is not None, "reassembly_story_state_missing")
        constraints = app.state.projects.load_constraints(project_id)
        formal_events = service._short_formal_event_authority(project, state.data)
        segment_count = service._short_segment_count(int(project.metadata["target_words"]))
        _require(segment_count == 1, "reassembly_segment_count_mismatch")
        brief = _build_brief(project, state.data, formal_events)
        formal_ending = service._short_formal_ending_authority(
            state.data, formal_events,
        )
        run_paths = [
            path for path in (project_path / "runs").iterdir()
            if path.is_dir() and (path / "outputs" / "conversion-audits").is_dir()
        ]
        _require(len(run_paths) == 1, "reassembly_source_run_not_unique")
        run_path = run_paths[0]
        try:
            await service._plan_short_ir_first_capacity_split(
                run_path.name, run_path, project, constraints, brief,
                formal_events, formal_ending, segment_count, 3000,
                {"trigger": "provider"},
            )
        except _CapturedRequest:
            pass
        _require(gateway.capture is not None, "request_reassembly_not_captured")
        _require(secrets.lookup_count == 0, "preflight_external_action_nonzero")
        return {
            **gateway.capture,
            "formal_events": formal_events,
            "formal_ending": formal_ending,
            "owned_event_count": len(formal_events),
        }


def reassemble_boundary_12_request(source_root: Path) -> dict[str, Any]:
    source_root = source_root.resolve(strict=True)
    required = (
        source_root / "db" / "app.db",
        source_root / "projects",
        source_root / "skills",
        source_root / "constraints-source.md",
    )
    _require(all(path.exists() for path in required), "reassembly_source_incomplete")
    with tempfile.TemporaryDirectory(prefix="r1-ptr4-probe-reassembly-") as raw:
        clone = Path(raw) / "source"
        clone.mkdir()
        shutil.copytree(source_root / "db", clone / "db")
        shutil.copytree(source_root / "projects", clone / "projects")
        shutil.copytree(source_root / "skills", clone / "skills")
        shutil.copy2(
            source_root / "constraints-source.md", clone / "constraints-source.md",
        )
        captured = asyncio.run(_capture_base_request(clone))
    base_system = str(captured["system"])
    user = str(captured["user"])
    target_system = _protocol_regeneration_system(base_system)
    base_system_sha = hashlib.sha256(base_system.encode("utf-8")).hexdigest()
    target_system_sha = hashlib.sha256(target_system.encode("utf-8")).hexdigest()
    user_sha = hashlib.sha256(user.encode("utf-8")).hexdigest()
    _require(target_system_sha == SYSTEM_SHA256, "reassembly_system_sha256_mismatch")
    _require(user_sha == USER_SHA256, "reassembly_user_sha256_mismatch")
    receipt_body = {
        "schema": "ProviderCapabilityProbeRequestReassemblyReceiptV1",
        "version": 1,
        "status": "exact",
        "source_content_embedded": False,
        "base_system_sha256": base_system_sha,
        "target_system_sha256": target_system_sha,
        "target_user_sha256": user_sha,
        "target_boundary_identity_sha256": TARGET_SHA256,
        "definition_sha256": DEFINITION_SHA256,
        "fixture_sha256": FIXTURE_SHA256,
        "contract_sha256": (
            "f23bb155296d9df6bf8e8992108c651c3354fd4d791dc0bbbcc46d2943cd42c7"
        ),
        "tool_schema_sha256": (
            "5424046dc2054fb588e161be0ef09b4badc53b150c78dc9f6ca3866cca590311"
        ),
        "route_kind": "configured_fallback",
        "protocol": "anthropic",
        "execution_mode": "plain",
        "requested_max_output_tokens": MAX_OUTPUT_TOKENS,
        "raw_prompt_omitted": True,
        "raw_story_omitted": True,
        "raw_tool_arguments_omitted": True,
        "external_action_counters": {
            "credential_lookup_count": 0,
            "provider_client_creation_count": 0,
            "network_call_count": 0,
            "model_call_count": 0,
            "paid_model_call_count": 0,
        },
    }
    receipt = _sealed(
        "r1-ptr4-probe-real-request-reassembly-v1", receipt_body,
        "request_reassembly_receipt_sha256",
    )
    return {
        "system": target_system, "user": user,
        "formal_events": captured["formal_events"],
        "formal_ending": captured["formal_ending"],
        "owned_event_count": captured["owned_event_count"],
        "receipt": receipt,
    }


def _validate_live_route(live_database: Path) -> dict[str, Any]:
    identity = production_route_identity(
        Database(live_database), "planning", "configured_fallback",
    )
    _require(
        identity.get("provider_descriptor_hash") == PROVIDER_SHA256
        and identity.get("model_binding_hash") == MODEL_SHA256
        and identity.get("protocol") == "anthropic",
        "live_provider_model_route_mismatch",
    )
    return identity


def materialize_signed_authorization(
    *, repo_root: Path, packet_root: Path, output_root: Path,
    source_root: Path, live_database: Path, live_projects: Path,
) -> dict[str, Any]:
    _require(not output_root.exists(), "signed_output_root_already_exists")
    packet = verify_fresh_packet_exact(repo_root, packet_root)
    now = _utc_now()
    _require(
        _parse_utc(NOT_BEFORE) <= _parse_utc(now) <= _parse_utc(NOT_AFTER),
        "approval_outside_execution_window",
    )
    route = _validate_live_route(live_database)
    before = live_parity_manifest(
        database_path=live_database, project_root=live_projects,
    )
    request = reassemble_boundary_12_request(source_root)
    after = live_parity_manifest(
        database_path=live_database, project_root=live_projects,
    )
    _require(parity_equal(before, after), "live_parity_changed_during_preflight")
    output_root.mkdir(parents=True)
    authorization = output_root / "authorization"
    ledger = output_root / "approval-ledger"
    authorization.mkdir()
    ledger.mkdir()
    _write_json(
        authorization / "provider-capability-probe-request-reassembly-receipt-v1.json",
        request["receipt"],
    )
    executor_sha = file_sha256(Path(__file__))
    auth_record_sha = domain_sha256(
        "r1-ptr4-probe-real-user-authorization-record-v1", {
            "profile_id": PROFILE_ID,
            "cohort_id": COHORT_ID,
            "plan_sha256": PLAN_SHA256,
            "candidate_sha256": CANDIDATE_SHA256,
            "patch_template_sha256": PATCH_TEMPLATE_SHA256,
            "not_before": NOT_BEFORE,
            "not_after": NOT_AFTER,
            "maximum_runs": 1,
            "maximum_total_model_calls": 1,
            "maximum_output_tokens": MAX_OUTPUT_TOKENS,
            "first_terminal_stop": True,
            "second_run_allowed": False,
            "resume_after_terminal": False,
            "approval_method": "explicit_final_user_authorization_in_current_task",
        },
    )
    patch = _sealed(
        "r1-ptr4-probe-real-confirmed-authorization-patch-v1", {
            "schema": "ProviderCapabilityProbeConfirmedAuthorizationPatchV1",
            "version": 1,
            "profile_id": PROFILE_ID,
            "single_use_cohort_id": COHORT_ID,
            "bound_plan_sha256": PLAN_SHA256,
            "bound_approval_candidate_sha256": CANDIDATE_SHA256,
            "bound_authorization_patch_template_sha256": PATCH_TEMPLATE_SHA256,
            "bound_request_reassembly_receipt_sha256": request["receipt"][
                "request_reassembly_receipt_sha256"
            ],
            "authorization_record_sha256": auth_record_sha,
            "confirmed_at": now,
            "execution_window": {"not_before": NOT_BEFORE, "not_after": NOT_AFTER},
            "execution_authorized": True,
            "authorize_credential_lookup": True,
            "authorize_provider_client_creation": True,
            "authorize_network": True,
            "authorize_model_call": True,
            "authorize_paid_model_call": True,
            "maximum_executions": 1,
            "maximum_total_model_calls": 1,
            "maximum_output_tokens": MAX_OUTPUT_TOKENS,
            "retry_allowed": False,
            "resume_allowed": False,
            "second_run_allowed": False,
            "full_short_allowed": False,
            "production_fix_allowed": False,
            "status": "confirmed_unused",
        }, "confirmed_authorization_patch_sha256",
    )
    _write_json(
        authorization / "provider-capability-probe-confirmed-authorization-patch-v1.json",
        patch,
    )
    ledger_identity = domain_sha256(
        "r1-ptr4-probe-real-operational-ledger-v1", {
            "packet_ledger_identity_sha256": packet["packet_ledger"][
                "ledger_identity_sha256"
            ],
            "cohort_id": COHORT_ID,
            "profile_id": PROFILE_ID,
        },
    )
    _write_json(ledger / ".provider-capability-probe-ledger-identity-v1.json", {
        "schema": "ProviderCapabilityProbeOperationalLedgerIdentityV1",
        "version": 1,
        "profile_id": PROFILE_ID,
        "cohort_id": COHORT_ID,
        "ledger_identity_sha256": ledger_identity,
    })
    signed = _sealed(
        "r1-ptr4-probe-real-signed-approval-v1", {
            "schema": "ProviderCapabilityProbeSignedApprovalV1",
            "version": 1,
            "profile_id": PROFILE_ID,
            "approval_scope": "provider_capability_probe",
            "single_use_cohort_id": COHORT_ID,
            "bound_plan_sha256": PLAN_SHA256,
            "source_approval_candidate_sha256": CANDIDATE_SHA256,
            "source_confirmed_authorization_patch_sha256": patch[
                "confirmed_authorization_patch_sha256"
            ],
            "bound_request_reassembly_receipt_sha256": request["receipt"][
                "request_reassembly_receipt_sha256"
            ],
            "bound_probe_definition_sha256": DEFINITION_SHA256,
            "bound_fixture_sha256": FIXTURE_SHA256,
            "bound_observer_schema_sha256": OBSERVER_SHA256,
            "bound_target_boundary_identity_sha256": TARGET_SHA256,
            "bound_provider_descriptor_hash": PROVIDER_SHA256,
            "bound_model_binding_hash": MODEL_SHA256,
            "bound_executor_source_sha256": executor_sha,
            "approval_ledger_identity_sha256": ledger_identity,
            "authorization_record_sha256": auth_record_sha,
            "named_approver": "final_user",
            "approval_method": "explicit_final_user_authorization_in_current_task",
            "signed_at": now,
            "execution_window": {"not_before": NOT_BEFORE, "not_after": NOT_AFTER},
            "usage_status": "unused",
            "reservation_status": "unreserved",
            "execution_authorized": True,
            "authorize_credential_lookup": True,
            "authorize_provider_client_creation": True,
            "authorize_network": True,
            "authorize_model_call": True,
            "authorize_paid_model_call": True,
            "approved_budget": {
                "maximum_runs": 1,
                "maximum_total_model_calls": 1,
                "maximum_input_tokens": MAX_INPUT_TOKENS,
                "maximum_output_tokens": MAX_OUTPUT_TOKENS,
                "maximum_output_tokens_per_call": MAX_OUTPUT_TOKENS,
                "maximum_usd_cost_microunits": MAX_USD_MICROUNITS,
                "maximum_cny_cost_microunits": MAX_CNY_MICROUNITS,
                "maximum_elapsed_seconds": MAX_ELAPSED_SECONDS,
            },
            "first_terminal_stop": True,
            "retry_allowed": False,
            "resume_after_terminal": False,
            "second_run_allowed": False,
            "full_short_allowed": False,
            "draft_review_maintenance_allowed": False,
            "production_fix_allowed": False,
            "maximum_executions": 1,
        }, "signed_approval_sha256",
    )
    _write_json(
        authorization / "provider-capability-probe-signed-approval-v1.json", signed,
    )
    receipt = validate_signed_authorization(
        repo_root=repo_root, packet_root=packet_root, output_root=output_root,
        source_root=source_root, live_database=live_database,
        live_projects=live_projects, persist=False,
    )
    _write_json(
        authorization / "provider-capability-probe-signed-validate-only-receipt-v1.json",
        receipt,
    )
    return {"patch": patch, "signed_approval": signed, "receipt": receipt}


def validate_signed_authorization(
    *, repo_root: Path, packet_root: Path, output_root: Path,
    source_root: Path, live_database: Path, live_projects: Path,
    persist: bool = False,
) -> dict[str, Any]:
    del persist
    packet = verify_fresh_packet_exact(repo_root, packet_root)
    authorization = output_root / "authorization"
    patch = _read_json(
        authorization / "provider-capability-probe-confirmed-authorization-patch-v1.json"
    )
    signed = _read_json(
        authorization / "provider-capability-probe-signed-approval-v1.json"
    )
    reassembly_stored = _read_json(
        authorization / "provider-capability-probe-request-reassembly-receipt-v1.json"
    )
    _require(
        patch.get("confirmed_authorization_patch_sha256") == _document_digest(
            "r1-ptr4-probe-real-confirmed-authorization-patch-v1", patch,
            "confirmed_authorization_patch_sha256",
        ), "confirmed_patch_hash_mismatch",
    )
    _require(
        signed.get("signed_approval_sha256") == _document_digest(
            "r1-ptr4-probe-real-signed-approval-v1", signed,
            "signed_approval_sha256",
        ), "signed_approval_hash_mismatch",
    )
    _require(
        signed.get("source_confirmed_authorization_patch_sha256")
        == patch.get("confirmed_authorization_patch_sha256")
        and signed.get("source_approval_candidate_sha256") == CANDIDATE_SHA256
        and signed.get("bound_plan_sha256") == PLAN_SHA256
        and signed.get("bound_executor_source_sha256") == file_sha256(Path(__file__)),
        "signed_source_binding_mismatch",
    )
    now = _utc_now()
    _require(
        _parse_utc(NOT_BEFORE) <= _parse_utc(now) <= _parse_utc(NOT_AFTER),
        "approval_outside_execution_window",
    )
    _require(
        signed.get("usage_status") == "unused"
        and signed.get("reservation_status") == "unreserved"
        and signed.get("maximum_executions") == 1
        and signed.get("maximum_total_model_calls") is None,
        "signed_approval_state_invalid",
    )
    # The total-call cap is nested in the approved budget; no top-level duplicate
    # is accepted because a second authority surface would be ambiguous.
    budget = signed.get("approved_budget") or {}
    _require(
        budget.get("maximum_total_model_calls") == 1
        and budget.get("maximum_input_tokens") == MAX_INPUT_TOKENS
        and budget.get("maximum_output_tokens") == MAX_OUTPUT_TOKENS
        and budget.get("maximum_output_tokens_per_call") == MAX_OUTPUT_TOKENS
        and budget.get("maximum_usd_cost_microunits") == MAX_USD_MICROUNITS
        and budget.get("maximum_cny_cost_microunits") == MAX_CNY_MICROUNITS
        and budget.get("maximum_elapsed_seconds") == MAX_ELAPSED_SECONDS,
        "signed_budget_mismatch",
    )
    _require(
        all(signed.get(field) is True for field in (
            "execution_authorized", "authorize_credential_lookup",
            "authorize_provider_client_creation", "authorize_network",
            "authorize_model_call", "authorize_paid_model_call",
            "first_terminal_stop",
        )), "signed_authorization_missing",
    )
    _require(
        signed.get("retry_allowed") is False
        and signed.get("resume_after_terminal") is False
        and signed.get("second_run_allowed") is False
        and signed.get("full_short_allowed") is False
        and signed.get("draft_review_maintenance_allowed") is False
        and signed.get("production_fix_allowed") is False,
        "signed_forbidden_scope_enabled",
    )
    route = _validate_live_route(live_database)
    before = live_parity_manifest(
        database_path=live_database, project_root=live_projects,
    )
    request = reassemble_boundary_12_request(source_root)
    after = live_parity_manifest(
        database_path=live_database, project_root=live_projects,
    )
    _require(parity_equal(before, after), "live_parity_changed_during_preflight")
    _require(request["receipt"] == reassembly_stored, "reassembly_receipt_changed")
    ledger = output_root / "approval-ledger"
    _require(
        (ledger / ".provider-capability-probe-ledger-identity-v1.json").is_file()
        and not (ledger / "reserved-v1.json").exists()
        and not (ledger / "consumed-v1.json").exists(),
        "operational_ledger_not_unused",
    )
    ordered = [
        ("fresh_packet", PLAN_SHA256),
        ("confirmed_patch", patch["confirmed_authorization_patch_sha256"]),
        ("signed_approval", signed["signed_approval_sha256"]),
        ("execution_window", signed["authorization_record_sha256"]),
        ("definition_fixture_observer_target", TARGET_SHA256),
        ("provider_model_route", route["model_binding_hash"]),
        ("request_reassembly", request["receipt"]["request_reassembly_receipt_sha256"]),
        ("budget_and_stop", packet["candidate"]["approved_budget"]["definition_sha256"]),
        ("ledger_unused", signed["approval_ledger_identity_sha256"]),
        ("live_parity", after["parity_sha256"]),
        ("external_actions_zero", None),
    ]
    body = {
        "schema": "ProviderCapabilityProbeSignedValidateOnlyReceiptV1",
        "version": 1,
        "overall_status": "exact",
        "validated_at": now,
        "profile_id": PROFILE_ID,
        "single_use_cohort_id": COHORT_ID,
        "bound_plan_sha256": PLAN_SHA256,
        "bound_signed_approval_sha256": signed["signed_approval_sha256"],
        "bound_confirmed_authorization_patch_sha256": patch[
            "confirmed_authorization_patch_sha256"
        ],
        "request_reassembly_receipt_sha256": request["receipt"][
            "request_reassembly_receipt_sha256"
        ],
        "approval_state": "signed_approval_exact_and_executable",
        "cohort_usage_status": "unused",
        "approval_reservation_status": "unreserved",
        "ledger_entry_count": 0,
        "live_parity_sha256": after["parity_sha256"],
        "ordered_checks": [
            {"name": name, "status": "exact", "evidence_sha256": evidence}
            for name, evidence in ordered
        ],
        "external_action_counters": {
            "credential_lookup_count": 0,
            "provider_client_creation_count": 0,
            "network_call_count": 0,
            "model_call_count": 0,
            "paid_model_call_count": 0,
        },
        "raw_prompt_omitted": True,
        "raw_story_omitted": True,
        "raw_tool_arguments_omitted": True,
        "raw_provider_response_omitted": True,
    }
    return _sealed(
        "r1-ptr4-probe-real-signed-validate-only-receipt-v1", body,
        "signed_validate_only_receipt_sha256",
    )


def _exclusive_write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(
            dict(value), ensure_ascii=False, sort_keys=True, indent=2,
            allow_nan=False,
        ) + "\n")


def _block_metadata_from_body(body: Mapping[str, Any]) -> tuple[list[dict], str, int]:
    content = body.get("content") or []
    blocks: list[dict] = []
    for item in content if isinstance(content, list) else []:
        if not isinstance(item, Mapping):
            continue
        kind = str(item.get("type") or "unknown")
        tool_present = kind in {"tool_use", "tool_call", "function_call"} and (
            "input" in item or "arguments" in item
        )
        argument = item.get("input", item.get("arguments"))
        argument_bytes = len(json.dumps(
            argument, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")) if tool_present else 0
        blocks.append({
            "block_type": kind,
            "visible_text_characters": (
                len(str(item.get("text") or ""))
                if kind in {"text", "output_text"} else 0
            ),
            "tool_arguments_present": tool_present,
            "tool_argument_byte_length": argument_bytes,
            "partial_tool_arguments": bool(
                kind in {"tool_use", "tool_call", "function_call"}
                and (not item.get("name") or not tool_present)
            ),
        })
    usage = body.get("usage") or {}
    return blocks, str(body.get("stop_reason") or body.get("finish_reason") or "unknown"), int(usage.get("output_tokens") or 0)


def _block_metadata_from_events(events: list[dict]) -> tuple[list[dict], str, int]:
    by_index: dict[int, dict[str, Any]] = {}
    finish = "unknown"
    output_tokens = 0
    for event in events:
        if not isinstance(event, Mapping):
            continue
        kind = event.get("type")
        if kind == "content_block_start":
            index = int(event.get("index") or 0)
            block = event.get("content_block") or {}
            block_type = str(block.get("type") or "unknown")
            by_index[index] = {
                "block_type": block_type,
                "visible_text_characters": len(str(block.get("text") or "")),
                "tool_arguments_present": "input" in block,
                "tool_argument_byte_length": (
                    len(json.dumps(
                        block.get("input"), ensure_ascii=False, sort_keys=True,
                        separators=(",", ":"), allow_nan=False,
                    ).encode("utf-8")) if "input" in block else 0
                ),
                "partial_tool_arguments": False,
            }
        elif kind == "content_block_delta":
            index = int(event.get("index") or 0)
            delta = event.get("delta") or {}
            block = by_index.setdefault(index, {
                "block_type": "unknown", "visible_text_characters": 0,
                "tool_arguments_present": False,
                "tool_argument_byte_length": 0,
                "partial_tool_arguments": False,
            })
            delta_type = delta.get("type")
            if delta_type in {"text_delta", "output_text_delta"}:
                block["visible_text_characters"] += len(str(delta.get("text") or ""))
            elif delta_type == "input_json_delta":
                raw = str(delta.get("partial_json") or "")
                block["tool_arguments_present"] = bool(raw) or block[
                    "tool_arguments_present"
                ]
                block["tool_argument_byte_length"] += len(raw.encode("utf-8"))
                block["partial_tool_arguments"] = True
        elif kind == "content_block_stop":
            index = int(event.get("index") or 0)
            if index in by_index:
                by_index[index]["partial_tool_arguments"] = False
        elif kind == "message_delta":
            delta = event.get("delta") or {}
            finish = str(delta.get("stop_reason") or finish)
            usage = event.get("usage") or {}
            output_tokens = int(usage.get("output_tokens") or output_tokens)
    return [by_index[index] for index in sorted(by_index)], finish, output_tokens


def _post_adapter_reachability(
    text: str, _formal_events: list[dict], owned_event_count: int,
) -> dict[str, bool]:
    parser_reached = True
    json_conversion = False
    wire_schema = False
    semantic_validation = False
    try:
        payload = parse_json_object(text)
        json_conversion = True
        normalized = normalize_planning_semantic_v2_payload(payload)
        _require(normalized is not None, "planning_semantic_v2_normalization_failed")
        semantic = PlanningSemanticDraftV2.model_validate(normalized)
        wire_schema = True
        merged = merge_planning_semantic_event_packets_v2(
            [semantic], [tuple(range(1, owned_event_count + 1))],
        )
        semantic_validation = (
            merged.model_dump(mode="json") == semantic.model_dump(mode="json")
        )
    except Exception:
        pass
    return {
        "parser_reached": parser_reached,
        "json_conversion_reached": json_conversion,
        "wire_schema_reached": wire_schema,
        "semantic_validation_reached": semantic_validation,
    }


async def _execute_one_provider_call(
    *, live_database: Path, request_data: Mapping[str, Any],
    counters: dict[str, int],
) -> dict[str, Any]:
    estimated_input = estimate_input_tokens(
        str(request_data["system"]) + "\n" + str(request_data["user"]),
    )
    _require(estimated_input <= MAX_INPUT_TOKENS, "maximum_input_tokens_preflight_exceeded")
    db = Database(live_database)
    binding = db.get_role_binding("planning") or {}
    provider_id = str(binding.get("fallback_provider_id") or "")
    model_id = str(binding.get("fallback_model_id") or "")
    _require(bool(provider_id and model_id), "configured_fallback_not_available")

    class CountingSecrets:
        def __init__(self) -> None:
            self.delegate = KeyringSecretStore()

        def get(self, selected_provider_id: str) -> str | None:
            counters["credential_lookup_count"] += 1
            return self.delegate.get(selected_provider_id)

        def set(self, _provider_id: str, _value: str) -> None:
            raise ProviderCapabilityProbeRealError("credential_mutation_forbidden")

        def delete(self, _provider_id: str) -> None:
            raise ProviderCapabilityProbeRealError("credential_mutation_forbidden")

    registry = ProviderRegistry(db, CountingSecrets())
    resolved = registry.resolve(provider_id, model_id)
    counters["provider_client_creation_count"] += 1
    route = _validate_live_route(live_database)
    catalog = production_price_catalog()
    price = catalog.require(route["provider_alias"], route["model_alias"], "default")
    worst = price.cost_microunits(
        input_tokens=MAX_INPUT_TOKENS, cached_input_tokens=0,
        output_tokens=MAX_OUTPUT_TOKENS, reasoning_tokens=0,
    )
    limit = (
        MAX_USD_MICROUNITS if price.currency == "USD" else MAX_CNY_MICROUNITS
        if price.currency == "CNY" else 0
    )
    _require(limit > 0 and worst <= limit, "maximum_cost_preflight_exceeded")
    capture: dict[str, Any] = {}
    original_post_stream = resolved.adapter.post_stream

    async def observed_post_stream(path: str, *, payload: dict, headers: dict):
        _require(path in {"messages", "v1/messages"}, "provider_path_mismatch")
        _require(payload.get("max_tokens") == MAX_OUTPUT_TOKENS, "provider_budget_mismatch")
        _require(payload.get("stream") is True, "provider_stream_mode_mismatch")
        _require("tools" not in payload and "output_config" not in payload, "provider_execution_mode_mismatch")
        _require(
            hashlib.sha256(str(payload.get("system") or "").encode("utf-8")).hexdigest()
            == SYSTEM_SHA256,
            "provider_system_sha256_mismatch",
        )
        messages = payload.get("messages") or []
        _require(len(messages) == 1 and messages[0].get("role") == "user", "provider_user_shape_mismatch")
        _require(
            hashlib.sha256(str(messages[0].get("content") or "").encode("utf-8")).hexdigest()
            == USER_SHA256,
            "provider_user_sha256_mismatch",
        )
        counters["network_call_count"] += 1
        counters["model_call_count"] += 1
        counters["paid_model_call_count"] += 1
        events, body = await original_post_stream(path, payload=payload, headers=headers)
        if isinstance(body, Mapping):
            blocks, finish, output = _block_metadata_from_body(body)
        else:
            blocks, finish, output = _block_metadata_from_events(events)
        capture.update({"blocks": blocks, "finish_reason": finish, "output_tokens": output})
        return events, body

    resolved.adapter.post_stream = observed_post_stream
    model_request = ModelRequest(
        model=resolved.model_name,
        messages=[
            Message(role="system", content=str(request_data["system"])),
            Message(role="user", content=str(request_data["user"])),
        ],
        max_output_tokens=MAX_OUTPUT_TOKENS,
    )
    response = await resolved.adapter.complete(model_request)
    if not capture:
        state = response.provider_state or {}
        blocks, finish, output = _block_metadata_from_body({
            "content": state.get("content") or [],
            "stop_reason": response.finish_reason,
            "usage": {"output_tokens": response.output_tokens},
        })
        capture.update({"blocks": blocks, "finish_reason": finish, "output_tokens": output})
    return {
        "capture": capture,
        "adapter_visible_characters": len(response.text or ""),
        "adapter_tool_arguments_present": bool(response.tool_calls),
        "input_tokens": int(response.input_tokens or 0),
        "output_tokens": int(response.output_tokens or capture.get("output_tokens") or 0),
        "reachability": _post_adapter_reachability(
            response.text or "", list(request_data["formal_events"]),
            int(request_data["owned_event_count"]),
        ),
        "cost_currency": price.currency,
        "actual_cost_microunits": price.cost_microunits(
            input_tokens=int(response.input_tokens or 0), cached_input_tokens=0,
            output_tokens=int(response.output_tokens or 0), reasoning_tokens=0,
        ),
        "maximum_cost_microunits": limit,
    }


def execute_real_probe_once(
    *, repo_root: Path, packet_root: Path, output_root: Path,
    source_root: Path, live_database: Path, live_projects: Path,
) -> dict[str, Any]:
    signed_receipt = validate_signed_authorization(
        repo_root=repo_root, packet_root=packet_root, output_root=output_root,
        source_root=source_root, live_database=live_database,
        live_projects=live_projects,
    )
    _require(signed_receipt.get("overall_status") == "exact", "signed_validate_not_exact")
    signed = _read_json(
        output_root / "authorization" / "provider-capability-probe-signed-approval-v1.json"
    )
    request = reassemble_boundary_12_request(source_root)
    before = live_parity_manifest(
        database_path=live_database, project_root=live_projects,
    )
    ledger = output_root / "approval-ledger"
    reservation = _sealed(
        "r1-ptr4-probe-real-reservation-v1", {
            "schema": "ProviderCapabilityProbeReservationV1", "version": 1,
            "profile_id": PROFILE_ID, "cohort_id": COHORT_ID,
            "signed_approval_sha256": signed["signed_approval_sha256"],
            "reserved_at": _utc_now(), "status": "reserved",
        }, "reservation_receipt_sha256",
    )
    _exclusive_write(ledger / "reserved-v1.json", reservation)
    counters = {
        "credential_lookup_count": 0,
        "provider_client_creation_count": 0,
        "network_call_count": 0,
        "model_call_count": 0,
        "paid_model_call_count": 0,
    }
    started = time.monotonic()
    call_result: dict[str, Any] | None = None
    terminal_status = "unknown"
    failure_type_sha256: str | None = None
    try:
        call_result = asyncio.run(_execute_one_provider_call(
            live_database=live_database, request_data=request, counters=counters,
        ))
        terminal_status = "provider_response_observed"
    except BaseException as exc:
        terminal_status = "typed_provider_call_failure"
        failure_type_sha256 = domain_sha256(
            "r1-ptr4-probe-real-failure-type-v1", type(exc).__name__,
        )
    elapsed = int((time.monotonic() - started) * 1_000_000)
    _require(counters["model_call_count"] <= 1, "model_call_budget_exceeded")
    _require(counters["network_call_count"] <= 1, "network_call_budget_exceeded")
    _require(counters["paid_model_call_count"] <= 1, "paid_call_budget_exceeded")
    _require(elapsed <= MAX_ELAPSED_SECONDS * 1_000_000, "elapsed_budget_exceeded")
    definition = build_provider_capability_probe_definition_v1(repo_root)
    fixture = build_provider_capability_probe_fixture_v1(repo_root, definition)
    observation: dict[str, Any] | None
    if call_result is not None:
        capture = call_result["capture"]
        observation = build_provider_capability_probe_observation_v1(
            definition=definition, fixture=fixture,
            blocks=[ProviderContentBlockMetadataV1.model_validate(item) for item in capture["blocks"]],
            finish_reason=capture["finish_reason"],
            output_tokens=call_result["output_tokens"],
            effective_provider_max_output_tokens=None,
            adapter_visible_characters=call_result["adapter_visible_characters"],
            adapter_tool_arguments_present=call_result["adapter_tool_arguments_present"],
            provider_capability_evidence_status="real_probe_observed",
            strict_tool_reached=False,
            **call_result["reachability"],
        ).model_dump(mode="json", by_alias=True)
        cost = {
            "currency": call_result["cost_currency"],
            "actual_cost_microunits": call_result["actual_cost_microunits"],
            "maximum_cost_microunits": call_result["maximum_cost_microunits"],
            "status": (
                "within_budget"
                if call_result["actual_cost_microunits"] <= call_result["maximum_cost_microunits"]
                else "exceeded_after_call"
            ),
        }
        input_tokens = call_result["input_tokens"]
        output_tokens = call_result["output_tokens"]
    else:
        # A typed failure before a response must never be promoted into a
        # capability observation.  The terminal receipt still consumes the
        # single-use cohort, so no replay can occur.
        observation = None
        cost = {"currency": "unknown", "actual_cost_microunits": None, "maximum_cost_microunits": None, "status": "unknown_after_failure"}
        input_tokens = None
        output_tokens = None
    after = live_parity_manifest(
        database_path=live_database, project_root=live_projects,
    )
    _require(parity_equal(before, after), "live_parity_changed_after_probe")
    evidence_body = {
        "schema": "ProviderCapabilityProbeRealExecutionReceiptV1",
        "version": 1,
        "profile_id": PROFILE_ID,
        "cohort_id": COHORT_ID,
        "signed_approval_sha256": signed["signed_approval_sha256"],
        "signed_validate_only_receipt_sha256": signed_receipt[
            "signed_validate_only_receipt_sha256"
        ],
        "reservation_receipt_sha256": reservation["reservation_receipt_sha256"],
        "request_reassembly_receipt_sha256": request["receipt"][
            "request_reassembly_receipt_sha256"
        ],
        "observation_receipt_sha256": (
            observation["receipt_sha256"] if observation is not None else None
        ),
        "terminal_status": terminal_status,
        "failure_type_sha256": failure_type_sha256,
        "executed_at": _utc_now(),
        "executed_run_count": 1 if counters["model_call_count"] else 0,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "requested_max_output_tokens": MAX_OUTPUT_TOKENS,
        "effective_provider_max_output_tokens": None,
        "cost": cost,
        "elapsed_micros": elapsed,
        "external_action_counters": counters,
        "live_parity": {
            "status": "exact", "before_sha256": before["parity_sha256"],
            "after_sha256": after["parity_sha256"],
        },
        "full_short_canary": "NOT_EXECUTED",
        "production_fix": "NOT_IMPLEMENTED",
        "retry_performed": False,
        "resume_performed": False,
        "second_run_performed": False,
        "raw_prompt_omitted": True,
        "raw_story_omitted": True,
        "raw_tool_arguments_omitted": True,
        "raw_provider_response_omitted": True,
    }
    evidence = _sealed(
        "r1-ptr4-probe-real-execution-receipt-v1", evidence_body,
        "execution_receipt_sha256",
    )
    reports = output_root / "reports"
    if observation is not None:
        _write_json(
            reports / "provider-capability-probe-observation-v1.json", observation,
        )
    _write_json(reports / "provider-capability-probe-real-execution-receipt-v1.json", evidence)
    consumption = _sealed(
        "r1-ptr4-probe-real-consumption-v1", {
            "schema": "ProviderCapabilityProbeConsumptionV1", "version": 1,
            "profile_id": PROFILE_ID, "cohort_id": COHORT_ID,
            "signed_approval_sha256": signed["signed_approval_sha256"],
            "reservation_receipt_sha256": reservation["reservation_receipt_sha256"],
            "execution_receipt_sha256": evidence["execution_receipt_sha256"],
            "consumed_at": _utc_now(), "status": "consumed",
        }, "consumption_receipt_sha256",
    )
    _exclusive_write(ledger / "consumed-v1.json", consumption)
    return {"observation": observation, "execution": evidence, "consumption": consumption}


def _cli() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("materialize", "validate", "execute"))
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--packet-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--live-database", type=Path, required=True)
    parser.add_argument("--live-projects", type=Path, required=True)
    args = parser.parse_args()
    common = {
        "repo_root": args.repo_root.resolve(),
        "packet_root": args.packet_root.resolve(),
        "output_root": args.output_root.resolve(),
        "source_root": args.source_root.resolve(),
        "live_database": args.live_database.resolve(),
        "live_projects": args.live_projects.resolve(),
    }
    if args.command == "materialize":
        result = materialize_signed_authorization(**common)
        public = {
            "gate": "R1_PTR4_PROVIDER_CAPABILITY_PROBE_SIGNED_VALIDATE_EXACT",
            "signed_approval_sha256": result["signed_approval"]["signed_approval_sha256"],
            "confirmed_patch_sha256": result["patch"]["confirmed_authorization_patch_sha256"],
            "signed_validate_only_receipt_sha256": result["receipt"]["signed_validate_only_receipt_sha256"],
            "external_action_counters": result["receipt"]["external_action_counters"],
        }
    elif args.command == "validate":
        result = validate_signed_authorization(**common)
        public = {
            "gate": "R1_PTR4_PROVIDER_CAPABILITY_PROBE_SIGNED_VALIDATE_EXACT",
            "signed_validate_only_receipt_sha256": result["signed_validate_only_receipt_sha256"],
            "external_action_counters": result["external_action_counters"],
        }
    else:
        result = execute_real_probe_once(**common)
        public = {
            "gate": "R1_PTR4_PROVIDER_CAPABILITY_PROBE_EXECUTION_TERMINAL",
            "execution_receipt_sha256": result["execution"]["execution_receipt_sha256"],
            "observation_receipt_sha256": (
                result["observation"]["receipt_sha256"]
                if result["observation"] is not None else None
            ),
            "terminal_status": result["execution"]["terminal_status"],
            "external_action_counters": result["execution"]["external_action_counters"],
            "full_short_canary": "NOT_EXECUTED",
            "production_fix": "NOT_IMPLEMENTED",
        }
    print(json.dumps(public, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
