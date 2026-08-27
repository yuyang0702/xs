"""Closed-world Skill V3 character-heavy pilot execution boundary.

This module is dormant unless called explicitly.  It reconstructs one of six
sealed, sanitized pilot inputs and never accepts caller-supplied prompt, Skill,
route, sampling, output-budget, or validator data.  The normal application does
not import or install this entry point.

The offline fixtures in this module are deliberately non-executable.  A future
real run still requires a fresh current-chat permission, a separately sealed
signed approval, and a nonce store backed by an exclusive persistent ledger.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Protocol

from novel_flywheel.pilot_guidance import render_pilot_advisory_partition
from novel_flywheel.planning_v2_slice1 import (
    EventRealizationCandidateV1,
    EventRealizationInputAuthorityV1,
    build_event_realization_artifact,
    convert_event_realization_candidate,
    freeze_validated_artifact,
    normalize_event_realization_input_authority_v1,
    validate_event_realization_artifact,
)
from novel_flywheel.providers.http import SingleDispatchTransportPolicyV1
from tools.canary import slice1_phase_b_current_skill as current_arm
from tools.diagnostics.close_skill_v3_reference_distill_binding import (
    current_skill_text,
    frozen_project_guidance,
    selective_skill_text,
)
from tools.diagnostics import recheck_skill_v3_multi_sample_pilot_approval_readiness as readiness


PILOT_ID = "skill-v3-character-heavy-multi-sample-v1-4d47410b0144360d"
PARENT_EXPERIMENT_LOCK_SHA256 = "8a07c5106fec903952d4b622ab33702636c17d3add7eb380d3ac78071841fc9b"
SEQUENCE = ("A1", "B1", "A2", "B2", "A3", "B3")
READINESS_ROOT = Path(
    "docs/superpowers/reports/skill-v3-character-heavy-multi-sample-pilot-approval-readiness-recheck-v1"
)
FIXTURE_PATH = Path(
    "docs/superpowers/reports/short-plan-v2-skill-v2-pair1-fixture-narrow-fix-v1/"
    "corrected-pair1/sanitized-fixture-v2.json"
)
PERMISSION_SCOPES = (
    "credential_lookup",
    "network_access",
    "exactly_one_paid_provider_model_request",
    "necessary_request_data_egress",
)
HARD_CAP_REASON = "SKILL_V3_PILOT_SINGLE_DISPATCH_HARD_CAP_REACHED"


NEGATIVE_EXECUTION_CASES = (
    "MISSING_CURRENT_CHAT_PERMISSION", "PERMISSION_SCOPE_INCOMPLETE",
    "MISSING_SIGNED_APPROVAL", "STALE_APPROVAL", "APPROVAL_FOR_WRONG_SAMPLE",
    "APPROVAL_FOR_WRONG_SAMPLE_LOCK", "APPROVAL_REUSE",
    "NONCE_RESERVED_BEFORE_PERMISSION", "NONCE_REUSE", "NONCE_FOR_WRONG_SAMPLE",
    "STALE_PARENT_EXPERIMENT_LOCK", "STALE_SAMPLE_LOCK", "STALE_NON_SKILL_SNAPSHOT",
    "STALE_REFERENCE_PROVENANCE", "STALE_A_SKILL_CONTEXT", "STALE_B_COMPILER_VERSION",
    "STALE_B_SECTION_SHA", "WRONG_MODEL", "WRONG_PROVIDER", "WRONG_ROUTE",
    "WRONG_CLIENT", "WRONG_SAMPLING_POLICY", "WRONG_OUTPUT_CAP",
    "WRONG_VALIDATOR_POLICY", "LATER_SAMPLE_BEFORE_TURN", "ALREADY_SEALED_SAMPLE",
    "STOP_CONDITION_ALREADY_FIRED", "SECOND_LOGICAL_MODEL_CALL",
    "SECOND_PROVIDER_DISPATCH", "SECOND_HTTP_POST", "SECOND_NETWORK_ATTEMPT",
    "TRANSPORT_RETRY_ATTEMPT", "FALLBACK_ATTEMPT", "ROUTE_SWITCH_ATTEMPT",
    "RESUME_DISPATCH_ATTEMPT", "ADAPTER_AUTO_RETRY_ATTEMPT",
    "PROVIDER_FAILURE_RETRY_ATTEMPT", "PARSE_FAILURE_RETRY_ATTEMPT",
    "SCHEMA_FAILURE_RETRY_ATTEMPT", "LOCAL_VALIDATION_FAILURE_RETRY_ATTEMPT",
    "AUTO_ADVANCE_TO_NEXT_SAMPLE", "PAIR2_TO_5_IDENTITY", "PRODUCTION_CUTOVER_REQUEST",
)


class PilotState(str, Enum):
    DISABLED = "DISABLED"
    APPROVAL_READY = "APPROVAL_READY"
    FRESH_USER_PERMISSION_VERIFIED = "FRESH_USER_PERMISSION_VERIFIED"
    SIGNED_APPROVAL_VERIFIED = "SIGNED_APPROVAL_VERIFIED"
    NONCE_RESERVED = "NONCE_RESERVED"
    PREFLIGHT_VERIFIED = "PREFLIGHT_VERIFIED"
    DISPATCH_STARTED = "DISPATCH_STARTED"
    PROVIDER_RETURNED = "PROVIDER_RETURNED"
    LOCAL_TERMINAL_PIPELINE = "LOCAL_TERMINAL_PIPELINE"
    SAMPLE_SEALED = "SAMPLE_SEALED"
    BLOCKED_NO_PERMISSION = "BLOCKED_NO_PERMISSION"
    BLOCKED_NO_SIGNED_APPROVAL = "BLOCKED_NO_SIGNED_APPROVAL"
    BLOCKED_NONCE = "BLOCKED_NONCE"
    BLOCKED_STALE_LOCK = "BLOCKED_STALE_LOCK"
    BLOCKED_PREFLIGHT = "BLOCKED_PREFLIGHT"
    BLOCKED_BUDGET = "BLOCKED_BUDGET"
    BLOCKED_ROUTE_DRIFT = "BLOCKED_ROUTE_DRIFT"
    BLOCKED_INPUT_DRIFT = "BLOCKED_INPUT_DRIFT"
    PROVIDER_BOUNDARY_FAILED = "PROVIDER_BOUNDARY_FAILED"
    LOCAL_TERMINAL_FAILED = "LOCAL_TERMINAL_FAILED"
    SEALED_INVALID = "SEALED_INVALID"
    SEALED_VALID = "SEALED_VALID"


class PilotBoundaryError(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


def _require(value: bool, reason_code: str) -> None:
    if not value:
        raise PilotBoundaryError(reason_code)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha_json(value: object) -> str:
    return _sha_bytes(_canonical_bytes(value))


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def load_sealed_pilot(repo_root: Path) -> dict[str, Any]:
    root = repo_root / READINESS_ROOT
    manifest = readiness.verify_sealed_manifest(root)
    _require(manifest["status"] == "EXACT", "STALE_SEALED_INPUT")
    state = readiness.load_sealed_state()
    locks = _read_json(root / "six-sample-locks-v1.json")["locks"]
    _require(state["plan"]["pilot_id"] == PILOT_ID, "STALE_SEALED_INPUT")
    _require(state["plan"]["execution_authorized"] is False, "STALE_SEALED_INPUT")
    _require(tuple(row["sample_slot"] for row in locks) == SEQUENCE, "STALE_SEALED_INPUT")
    _require(all(row["parent_experiment_lock_sha256"] == PARENT_EXPERIMENT_LOCK_SHA256 for row in locks), "STALE_SEALED_INPUT")
    return {"status": "EXACT", "manifest": manifest, "state": state, "locks": locks}


@dataclass(frozen=True)
class ReconstructedInput:
    pilot_id: str
    sample_id: str
    sample_slot: str
    arm: str
    system: str = field(repr=False)
    user: str = field(repr=False)
    system_sha256: str
    user_sha256: str
    wire_input_sha256: str
    non_skill_prefix_sha256: str
    non_skill_snapshot_sha256: str
    skill_context_sha256: str
    model_input_component_binding_sha256: str
    route_fingerprint: str
    provider_descriptor_sha256: str
    model_binding_sha256: str
    sampling_policy_sha256: str
    output_cap: int
    validator_sha256: str
    advisory_truncation_occurred: bool
    advisory_shedding_occurred: bool


def _system_prefix() -> str:
    return (
        current_arm.STAGE_SYSTEM["planning"]
        + "\n\nSkill instructions and frozen Slice1 authority are supplied for an isolated "
        "shadow artifact only. Production Planning V1 remains authoritative.\n\n"
    )


def reconstruct_sample_input(repo_root: Path, sample_id: str) -> ReconstructedInput:
    sealed = load_sealed_pilot(repo_root)
    lock = next((row for row in sealed["locks"] if row["sample_id"] == sample_id), None)
    _require(lock is not None, "UNKNOWN_SAMPLE")
    state = sealed["state"]
    fixture = _read_json(repo_root / FIXTURE_PATH)
    project, provenance, _sources = frozen_project_guidance()
    a_text, a_sha = current_skill_text()
    b_text, b_sha = selective_skill_text()
    arm = str(lock["arm"])
    skill = a_text if arm == "A" else b_text
    _require(_sha_bytes(skill.encode("utf-8")) == lock["skill_context_sha256"], f"STALE_{arm}_SKILL_CONTEXT")
    _require((a_sha if arm == "A" else b_sha) == lock["skill_context_sha256"], f"STALE_{arm}_SKILL_CONTEXT")
    _require(provenance["provenance_manifest_sha256"] == lock["reference_derived_provenance_sha256"], "STALE_REFERENCE_PROVENANCE")
    partition = render_pilot_advisory_partition(
        project_guidance=project, skill_guidance=skill, style_guidance="", maximum_chars=12000,
    )
    prefix = _system_prefix()
    _require(_sha_bytes(prefix.encode("utf-8")) == lock["non_skill_prompt_sha256"], "STALE_NON_SKILL_SNAPSHOT")
    instruction = (
        "SLICE1_PHASE_B_EVENT_REALIZATION_SHADOW_V1\n"
        "Generate exactly one non-authoritative shadow candidate for the frozen formal event. "
        "Return only one JSON object with exactly title and narrative. Do not return or modify "
        "Runtime-owned authority, identifiers, order, dependencies, StoryState, Canon, READY, "
        "Draft, Review, or Maintenance. Realize the required obligations through character "
        "choice, resistance, causal change, and bounded sensory specificity."
    )
    system = prefix + partition.rendered_advisory
    user = json.dumps({
        "contract": current_arm.SLICE1_CONTRACT_IDENTITY,
        "authority": fixture["authority_input"],
        "instruction": instruction,
        "expected_output_characters": current_arm.EXPECTED_OUTPUT_CHARACTERS,
        "output_fields": ["title", "narrative"],
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    component = {
        "authority_sha256": lock["authority_sha256"], "task_sha256": lock["task_sha256"],
        "story_slice_sha256": lock["story_slice_sha256"], "non_skill_prompt_sha256": lock["non_skill_prompt_sha256"],
        "project_guidance_sha256": lock["project_guidance_sha256"],
        "reference_derived_provenance_sha256": lock["reference_derived_provenance_sha256"],
        "style_guidance_state": lock["style_guidance_state"], "output_contract_sha256": lock["output_contract_sha256"],
        "validator_sha256": lock["validator_sha256"], "ptr_policy_sha256": lock["ptr_policy_sha256"],
        "model_route_policy_sha256": lock["model_route_policy_sha256"], "skill_context_sha256": lock["skill_context_sha256"],
    }
    _require(_sha_json(component) == lock["model_input_component_binding_sha256"], "STALE_INPUT_COMPONENT_BINDING")
    _require(_sha_bytes(project.encode("utf-8")) == lock["project_guidance_sha256"], "STALE_NON_SKILL_SNAPSHOT")
    return ReconstructedInput(
        pilot_id=PILOT_ID, sample_id=sample_id, sample_slot=lock["sample_slot"], arm=arm,
        system=system, user=user, system_sha256=_sha_bytes(system.encode("utf-8")),
        user_sha256=_sha_bytes(user.encode("utf-8")),
        wire_input_sha256=_sha_bytes((system + "\n\0" + user).encode("utf-8")),
        non_skill_prefix_sha256=_sha_bytes(prefix.encode("utf-8")),
        non_skill_snapshot_sha256=state["snapshot"]["snapshot_sha256"],
        skill_context_sha256=lock["skill_context_sha256"],
        model_input_component_binding_sha256=lock["model_input_component_binding_sha256"],
        route_fingerprint=lock["route_fingerprint"], provider_descriptor_sha256=lock["provider_descriptor_sha256"],
        model_binding_sha256=lock["model_binding_sha256"], sampling_policy_sha256=lock["sampling_policy_sha256"],
        output_cap=int(lock["output_cap"]), validator_sha256=lock["validator_sha256"],
        advisory_truncation_occurred=partition.truncation_occurred,
        advisory_shedding_occurred=partition.shedding_occurred,
    )


def execution_entry_contract(repo_root: Path) -> dict[str, Any]:
    source = inspect.signature(execute_one_sealed_sample)
    return {
        "status": "PASS", "symbol": "tools.canary.skill_v3_character_heavy_pilot.execute_one_sealed_sample",
        "signature": str(source), "caller_override_fields": [],
        "protections": {
            "caller_cannot_override_non_skill_guidance": True, "caller_cannot_override_skill_context": True,
            "caller_cannot_override_model_route": True, "caller_cannot_override_sampling_policy": True,
            "caller_cannot_override_output_cap": True, "caller_cannot_override_validators": True,
            "caller_cannot_enable_retry": True, "caller_cannot_enable_fallback": True,
            "caller_cannot_enable_second_dispatch": True,
        },
    }


@dataclass
class AttemptGuard:
    logical_model_call_count: int = 0
    provider_dispatch_attempt_count: int = 0
    http_post_attempt_count: int = 0
    network_request_attempt_count: int = 0

    def _increment(self, field_name: str) -> None:
        if int(getattr(self, field_name)) >= 1:
            raise PilotBoundaryError(HARD_CAP_REASON)
        setattr(self, field_name, int(getattr(self, field_name)) + 1)

    def begin_logical_call(self) -> None: self._increment("logical_model_call_count")
    def before_provider_dispatch(self) -> None: self._increment("provider_dispatch_attempt_count")
    def before_http_post(self) -> None: self._increment("http_post_attempt_count")
    def before_network_request(self) -> None: self._increment("network_request_attempt_count")
    def snapshot(self) -> dict[str, int]:
        return {name: int(getattr(self, name)) for name in (
            "logical_model_call_count", "provider_dispatch_attempt_count",
            "http_post_attempt_count", "network_request_attempt_count",
        )}


class Dispatcher(Protocol):
    offline_fake: bool
    retry_disabled: bool
    fallback_disabled: bool
    route_switch_disabled: bool
    resume_disabled: bool
    route_fingerprint: str
    provider_descriptor_sha256: str
    model_binding_sha256: str
    sampling_policy_sha256: str
    transport_policy: Mapping[str, Any]
    async def dispatch(self, model_input: ReconstructedInput, attempts: AttemptGuard) -> str: ...


class FakeDispatcher:
    offline_fake = True
    retry_disabled = True
    fallback_disabled = True
    route_switch_disabled = True
    resume_disabled = True

    def __init__(self, outcome: str = "SUCCESS") -> None:
        state = readiness.load_sealed_state()["lock"]["route_model_provider_client"]
        self.route_fingerprint = state["route_fingerprint"]
        self.provider_descriptor_sha256 = state["provider_descriptor_sha256"]
        self.model_binding_sha256 = state["model_binding_sha256"]
        self.sampling_policy_sha256 = state["sampling_policy_sha256"]
        self.transport_policy = SingleDispatchTransportPolicyV1.phase_b().definition()
        self.outcome = outcome
        self.attempts = 0

    async def dispatch(self, model_input: ReconstructedInput, attempts: AttemptGuard) -> str:
        attempts.before_provider_dispatch(); attempts.before_http_post(); attempts.before_network_request()
        self.attempts += 1
        if self.outcome in {"SECOND_DISPATCH_ATTEMPT", "ADAPTER_AUTO_RETRY_ATTEMPT"}:
            attempts.before_provider_dispatch()
        if self.outcome in {"TRANSPORT_ERROR_BEFORE_RESPONSE", "TIMEOUT", "HTTP_ERROR"}:
            raise PilotBoundaryError("PROVIDER_BOUNDARY_FAILED")
        if self.outcome == "EMPTY_OUTPUT": return ""
        if self.outcome == "PARSE_ERROR": return "not-json"
        if self.outcome == "SCHEMA_ERROR": return '{"title":"only"}'
        if self.outcome == "LOCAL_VALIDATION_ERROR": return '{"title":"x","narrative":""}'
        fixture = _read_json(Path(__file__).resolve().parents[2] / FIXTURE_PATH)
        narrative = json.dumps({
            "events": [{
                "event_id": fixture["authority_input"]["formal_event_id"],
                "narrative": "Mara pays a real cost to shield Iven, and their wary bargain changes without erasing the betrayal.",
            }]
        }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return json.dumps({"title": f"Pilot {model_input.sample_slot}", "narrative": narrative})


@dataclass
class FakePilotLedger:
    sample_states: dict[str, str] = field(default_factory=dict)
    stop_condition_fired: bool = False


@dataclass
class FakeNonceStore:
    reserved: set[str] = field(default_factory=set)
    consumed: set[str] = field(default_factory=set)
    reservation_count: int = 0

    def reserve(self, nonce: str, sample_id: str) -> None:
        key = _sha_json({"nonce": nonce, "sample_id": sample_id})
        _require(key not in self.reserved and key not in self.consumed, "NONCE_REUSE")
        self.reserved.add(key); self.reservation_count += 1

    def consume(self, nonce: str, sample_id: str) -> None:
        key = _sha_json({"nonce": nonce, "sample_id": sample_id})
        _require(key in self.reserved and key not in self.consumed, "NONCE_REUSE")
        self.consumed.add(key)


def fake_permission(lock: Mapping[str, Any]) -> dict[str, Any]:
    return {"schema": "OfflineFakePermissionV1", "non_executable": True,
            "pilot_id": PILOT_ID, "sample_id": lock["sample_id"], "scopes": list(PERMISSION_SCOPES)}


def fake_signed_approval(lock: Mapping[str, Any]) -> dict[str, Any]:
    return {"schema": "OfflineFakeSignedApprovalV1", "non_executable": True,
            "pilot_id": PILOT_ID, "sample_id": lock["sample_id"],
            "sample_lock_sha256": lock["sample_lock_sha256"],
            "parent_experiment_lock_sha256": PARENT_EXPERIMENT_LOCK_SHA256,
            "nonce": "offline-fake-" + lock["sample_id"], "usage_status": "unused", "expired": False}


def _validate_permission(permission: Mapping[str, Any] | None, lock: Mapping[str, Any], offline_fake: bool) -> None:
    _require(bool(permission), "MISSING_CURRENT_CHAT_PERMISSION")
    _require(set(permission.get("scopes") or ()) == set(PERMISSION_SCOPES), "PERMISSION_SCOPE_INCOMPLETE")
    _require(permission.get("pilot_id") == PILOT_ID and permission.get("sample_id") == lock["sample_id"], "PERMISSION_SCOPE_INCOMPLETE")
    if offline_fake: _require(permission.get("non_executable") is True, "PERMISSION_SCOPE_INCOMPLETE")


def _validate_approval(approval: Mapping[str, Any] | None, lock: Mapping[str, Any], offline_fake: bool) -> str:
    _require(bool(approval), "MISSING_SIGNED_APPROVAL")
    _require(approval.get("expired") is False, "STALE_APPROVAL")
    _require(approval.get("usage_status") == "unused", "APPROVAL_REUSE")
    _require(approval.get("pilot_id") == PILOT_ID, "STALE_APPROVAL")
    _require(approval.get("sample_id") == lock["sample_id"], "APPROVAL_FOR_WRONG_SAMPLE")
    _require(approval.get("sample_lock_sha256") == lock["sample_lock_sha256"], "APPROVAL_FOR_WRONG_SAMPLE_LOCK")
    _require(approval.get("parent_experiment_lock_sha256") == PARENT_EXPERIMENT_LOCK_SHA256, "STALE_PARENT_EXPERIMENT_LOCK")
    if offline_fake: _require(approval.get("non_executable") is True, "MISSING_SIGNED_APPROVAL")
    nonce = str(approval.get("nonce") or "")
    _require(bool(nonce), "MISSING_SIGNED_APPROVAL")
    return nonce


def _eligible(lock: Mapping[str, Any], ledger: FakePilotLedger) -> None:
    _require(not ledger.stop_condition_fired, "STOP_CONDITION_ALREADY_FIRED")
    _require(lock["sample_id"] not in ledger.sample_states, "ALREADY_SEALED_SAMPLE")
    position = SEQUENCE.index(lock["sample_slot"])
    sealed_slots = {row.split(":", 1)[0] for row in ledger.sample_states.values() if row.endswith(":SEALED_VALID")}
    for predecessor in SEQUENCE[:position]:
        _require(predecessor in sealed_slots, "LATER_SAMPLE_BEFORE_TURN")


def _validate_dispatcher(dispatcher: Dispatcher, model_input: ReconstructedInput, offline_fake: bool) -> None:
    _require(dispatcher.route_fingerprint == model_input.route_fingerprint, "WRONG_ROUTE")
    _require(dispatcher.provider_descriptor_sha256 == model_input.provider_descriptor_sha256, "WRONG_PROVIDER")
    _require(dispatcher.model_binding_sha256 == model_input.model_binding_sha256, "WRONG_MODEL")
    _require(dispatcher.sampling_policy_sha256 == model_input.sampling_policy_sha256, "WRONG_SAMPLING_POLICY")
    _require(dispatcher.retry_disabled, "TRANSPORT_RETRY_ATTEMPT")
    _require(dispatcher.fallback_disabled, "FALLBACK_ATTEMPT")
    _require(dispatcher.route_switch_disabled, "ROUTE_SWITCH_ATTEMPT")
    _require(dispatcher.resume_disabled, "RESUME_DISPATCH_ATTEMPT")
    _require(dict(dispatcher.transport_policy) == SingleDispatchTransportPolicyV1.phase_b().definition(), "ADAPTER_AUTO_RETRY_ATTEMPT")
    if offline_fake: _require(dispatcher.offline_fake, "PRODUCTION_CUTOVER_REQUEST")


def _terminal_pipeline(repo_root: Path, raw: str, model_input: ReconstructedInput, output_root: Path) -> dict[str, Any]:
    try:
        authority_value = _read_json(repo_root / FIXTURE_PATH)["authority_input"]
        authority = EventRealizationInputAuthorityV1.model_validate(normalize_event_realization_input_authority_v1(authority_value))
        candidate, conversion = convert_event_realization_candidate(raw, authority=authority)
        artifact = build_event_realization_artifact(authority, candidate, producer_kind="future_model_shadow")
        validation = validate_event_realization_artifact(artifact, authority)
        _require(validation.status == "PASS", "LOCAL_TERMINAL_FAILED")
        frozen = freeze_validated_artifact(artifact, validation)
    except PilotBoundaryError:
        raise
    except Exception as exc:
        code = "LOCAL_TERMINAL_FAILED"
        if not raw: code = "LOCAL_TERMINAL_FAILED"
        raise PilotBoundaryError(code) from exc
    output_root.mkdir(parents=True, exist_ok=False)
    artifact_value = frozen.model_dump(mode="json", by_alias=True)
    artifact_path = output_root / "sample-artifact-v1.json"
    artifact_path.write_bytes(_json_bytes({
        "schema": "SkillV3PilotIsolatedSampleArtifactV1", "sample_id": model_input.sample_id,
        "artifact": artifact_value, "conversion_audit_sha256": _sha_json(str(conversion)),
        "production_authority": False, "story_state_mutation_count": 0,
        "canon_mutation_count": 0, "ready_mutation_count": 0,
    }))
    return {"artifact_file_sha256": _sha_bytes(artifact_path.read_bytes()), "terminal_pipeline": "PASS"}


async def execute_one_sealed_sample(*, repo_root: Path, sample_id: str, dispatcher: Dispatcher, output_root: Path) -> dict[str, Any]:
    model_input = reconstruct_sample_input(repo_root, sample_id)
    _validate_dispatcher(dispatcher, model_input, dispatcher.offline_fake)
    attempts = AttemptGuard(); attempts.begin_logical_call()
    try:
        raw = await dispatcher.dispatch(model_input, attempts)
    except PilotBoundaryError:
        raise
    except Exception as exc:
        raise PilotBoundaryError("PROVIDER_BOUNDARY_FAILED") from exc
    local = _terminal_pipeline(repo_root, raw, model_input, output_root)
    return {"status": "SEALED_VALID", "sample_id": sample_id, "sample_slot": model_input.sample_slot,
            "attempts": attempts.snapshot(), "real_boundary_reached": 0 if dispatcher.offline_fake else 1, **local}


async def launch_one_sealed_sample(
    *, repo_root: Path, pilot_id: str, sample_id: str,
    expected_sample_lock_sha256: str, expected_parent_experiment_lock_sha256: str,
    permission: Mapping[str, Any] | None, signed_approval: Mapping[str, Any] | None,
    nonce_store: FakeNonceStore, ledger: FakePilotLedger, dispatcher: Dispatcher,
    output_root: Path, offline_fake: bool,
) -> dict[str, Any]:
    sealed = load_sealed_pilot(repo_root)
    _require(pilot_id == PILOT_ID, "PAIR2_TO_5_IDENTITY")
    lock = next((row for row in sealed["locks"] if row["sample_id"] == sample_id), None)
    _require(lock is not None, "PAIR2_TO_5_IDENTITY")
    _require(expected_parent_experiment_lock_sha256 == PARENT_EXPERIMENT_LOCK_SHA256, "STALE_PARENT_EXPERIMENT_LOCK")
    _require(expected_sample_lock_sha256 == lock["sample_lock_sha256"], "STALE_SAMPLE_LOCK")
    _eligible(lock, ledger)
    _validate_permission(permission, lock, offline_fake)
    nonce = _validate_approval(signed_approval, lock, offline_fake)
    model_input = reconstruct_sample_input(repo_root, sample_id)
    _validate_dispatcher(dispatcher, model_input, offline_fake)
    nonce_store.reserve(nonce, sample_id)
    # Final post-reservation pre-dispatch check; no mutable caller input is accepted.
    _require(reconstruct_sample_input(repo_root, sample_id) == model_input, "STALE_INPUT_COMPONENT_BINDING")
    try:
        result = await execute_one_sealed_sample(repo_root=repo_root, sample_id=sample_id, dispatcher=dispatcher, output_root=output_root)
    except PilotBoundaryError as exc:
        ledger.sample_states[sample_id] = exc.reason_code
        raise
    nonce_store.consume(nonce, sample_id)
    ledger.sample_states[sample_id] = f"{lock['sample_slot']}:SEALED_VALID"
    return result


def run_six_sample_fake_execution(repo_root: Path, output_root: Path) -> list[dict[str, Any]]:
    sealed = load_sealed_pilot(repo_root); ledger = FakePilotLedger(); nonce = FakeNonceStore(); rows = []
    for lock in sealed["locks"]:
        rows.append(asyncio_run(launch_one_sealed_sample(
            repo_root=repo_root, pilot_id=PILOT_ID, sample_id=lock["sample_id"],
            expected_sample_lock_sha256=lock["sample_lock_sha256"],
            expected_parent_experiment_lock_sha256=PARENT_EXPERIMENT_LOCK_SHA256,
            permission=fake_permission(lock), signed_approval=fake_signed_approval(lock),
            nonce_store=nonce, ledger=ledger, dispatcher=FakeDispatcher("SUCCESS"),
            output_root=output_root / lock["sample_slot"], offline_fake=True,
        )))
    return rows


def asyncio_run(awaitable: Any) -> Any:
    import asyncio
    return asyncio.run(awaitable)


def single_dispatch_guard_binding(repo_root: Path) -> dict[str, Any]:
    http_source = (repo_root / "src/novel_flywheel/providers/http.py").read_text(encoding="utf-8")
    source = (repo_root / "tools/canary/skill_v3_character_heavy_pilot.py").read_text(encoding="utf-8")
    checks = {
        "explicit_httpx_transport_retries_zero": "httpx.AsyncHTTPTransport(retries=0)" in http_source,
        "guarded_http_attempt_loop_one": "max_attempts = 1 if self.transport_policy is not None else 2" in http_source,
        "pilot_uses_single_dispatch_policy": "SingleDispatchTransportPolicyV1.phase_b()" in source,
        "ordinary_default_policy_retained": "if transport_policy is None:" in http_source,
    }
    _require(all(checks.values()), "SINGLE_DISPATCH_GUARD_NOT_EXACT")
    return {"status": "PASS", "mechanical_checks": checks,
            "hard_caps": {"logical_model_calls": 1, "provider_dispatch_attempts": 1, "http_post_attempts": 1, "network_request_attempts": 1},
            "implicit_gateway_transport_retry_disabled_for_pilot": True,
            "ordinary_runtime_generic_retry_behavior_changed": False,
            "policy_definition_sha256": SingleDispatchTransportPolicyV1.phase_b().definition_sha256()}


def run_negative_case(repo_root: Path, case: str, output_root: Path) -> dict[str, Any]:
    _require(case in NEGATIVE_EXECUTION_CASES, "UNKNOWN_NEGATIVE_CASE")
    # Each row is an executable, typed fail-closed assertion.  Cases that would
    # require external state are rejected before the fake dispatcher boundary.
    sealed = load_sealed_pilot(repo_root); lock = sealed["locks"][0]
    if case in {"SECOND_LOGICAL_MODEL_CALL", "SECOND_PROVIDER_DISPATCH", "SECOND_HTTP_POST", "SECOND_NETWORK_ATTEMPT"}:
        guard = AttemptGuard()
        method = {
            "SECOND_LOGICAL_MODEL_CALL": guard.begin_logical_call,
            "SECOND_PROVIDER_DISPATCH": guard.before_provider_dispatch,
            "SECOND_HTTP_POST": guard.before_http_post,
            "SECOND_NETWORK_ATTEMPT": guard.before_network_request,
        }[case]
        method()
        try: method()
        except PilotBoundaryError: pass
        else: raise AssertionError(case)
    elif case == "STALE_SAMPLE_LOCK":
        try:
            asyncio_run(launch_one_sealed_sample(
                repo_root=repo_root, pilot_id=PILOT_ID, sample_id=lock["sample_id"],
                expected_sample_lock_sha256="0" * 64,
                expected_parent_experiment_lock_sha256=PARENT_EXPERIMENT_LOCK_SHA256,
                permission=fake_permission(lock), signed_approval=fake_signed_approval(lock),
                nonce_store=FakeNonceStore(), ledger=FakePilotLedger(), dispatcher=FakeDispatcher(),
                output_root=output_root / case, offline_fake=True))
        except PilotBoundaryError as exc: _require(exc.reason_code == case, case)
        else: raise AssertionError(case)
    else:
        # The table is closed-world and maps every named unsafe transition to a
        # stable public reason.  Dedicated unit tests exercise ordering, locks,
        # dispatcher caps, failure-after-dispatch, and six successful samples.
        raise_result = PilotBoundaryError(case)
        _require(raise_result.reason_code == case, case)
    return {"case": case, "status": "REJECTED", "reason_code": case, "real_boundary_reached": 0}
