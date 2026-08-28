"""Dormant, closed-world boundary for the prospective Hybrid Skill V3 pilot.

The module reconstructs only the six sealed inputs.  It creates neither user
permission, signed approvals, nor durable nonces.  Real dispatch remains
impossible unless a future caller supplies all three through the existing
worktree-external one-shot boundary.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping, Protocol

from novel_flywheel.context_policy import estimate_input_tokens
from novel_flywheel.hybrid_skill_context import (
    SUPPLEMENT_SEPARATOR,
    HybridSkillContextCompilerV1,
    HybridSkillSectionIndexV2,
)
from novel_flywheel.pilot_guidance import render_pilot_advisory_partition
from novel_flywheel.providers.http import SingleDispatchTransportPolicyV1
from tools.canary import skill_v3_character_heavy_pilot as prior
from tools.diagnostics.close_skill_v3_reference_distill_binding import (
    frozen_project_guidance,
)
from tools.diagnostics.materialize_skill_v3_hybrid_independent_review_v2 import (
    INDEX_V1,
    INDEX_V2,
    _production_baseline,
    _request,
)


REPORT_ROOT = Path(
    "docs/superpowers/reports/"
    "skill-v3-hybrid-character-heavy-multi-sample-pilot-materialization-v1"
)
FIXTURE_PATH = prior.FIXTURE_PATH
SEQUENCE = (
    "CONTROL_1", "HYBRID_1", "CONTROL_2",
    "HYBRID_2", "CONTROL_3", "HYBRID_3",
)
PERMISSION_SCOPES = prior.PERMISSION_SCOPES
PILOT_ADVISORY_MAXIMUM_CHARS = 16_000
NONCE_POLICY_VERSION = prior.NONCE_POLICY_VERSION
REAL_DISPATCHER_VERSION = prior.REAL_DISPATCHER_VERSION


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha_json(value: object) -> str:
    return _sha_bytes(_canonical_bytes(value))


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise prior.PilotBoundaryError("STALE_SEALED_INPUT")
    return value


def _require(value: bool, reason: str) -> None:
    if not value:
        raise prior.PilotBoundaryError(reason)


def _git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    _require(result.returncode == 0, "HEAD_OR_WORKTREE_DRIFT")
    return result.stdout.strip()


def verify_manifest(root: Path) -> dict[str, Any]:
    envelope = _read_json(root / "sha256-manifest-v1.json")
    definition = envelope.get("definition")
    _require(isinstance(definition, dict), "STALE_SEALED_INPUT")
    entries = definition.get("entries")
    _require(isinstance(entries, list), "STALE_SEALED_INPUT")
    failures: list[str] = []
    covered: set[str] = set()
    for row in entries:
        relative = str(row["path"])
        covered.add(relative)
        path = root / relative
        if not path.is_file() or _sha_bytes(path.read_bytes()) != row["sha256"]:
            failures.append(relative)
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != "sha256-manifest-v1.json"
    }
    if actual != covered:
        failures.append("manifest_coverage")
    _require(not failures, "STALE_SEALED_INPUT")
    return {
        "status": "EXACT",
        "entry_count": len(entries),
        "definition_sha256": envelope["definition_sha256"],
    }


def load_sealed_pilot(repo_root: Path) -> dict[str, Any]:
    root = repo_root.resolve(strict=True) / REPORT_ROOT
    manifest = verify_manifest(root)
    identity = _read_json(root / "pilot-identity-v1.json")
    experiment = _read_json(root / "experiment-lock-v1.json")
    samples = _read_json(root / "fresh-sample-manifest-v1.json")
    approval = _read_json(root / "approval-readiness-packet-v1.json")
    _require(identity["PILOT_ID"] == experiment["PILOT_ID"], "STALE_SEALED_INPUT")
    _require(samples["PILOT_ID"] == identity["PILOT_ID"], "STALE_SEALED_INPUT")
    _require(tuple(row["SAMPLE_SLOT"] for row in samples["samples"]) == SEQUENCE,
             "STALE_SEALED_INPUT")
    _require(approval["EXECUTION_AUTHORIZED"] is False, "PILOT_EXECUTION_AUTHORIZED")
    _require(approval["SIGNED_APPROVAL_CREATED"] == "NO", "SIGNED_APPROVAL_PRESENT")
    _require(approval["REAL_NONCE_CREATED"] == "NO", "REAL_NONCE_PRESENT")
    source_bindings = experiment["definition"].get(
        "EXECUTION_BOUNDARY_SOURCE_BINDINGS"
    )
    _require(isinstance(source_bindings, dict) and bool(source_bindings),
             "STALE_EXECUTION_BOUNDARY")
    for relative, expected in source_bindings.items():
        path = repo_root.resolve(strict=True) / str(relative)
        _require(path.is_file() and _sha_bytes(path.read_bytes()) == expected,
                 "STALE_EXECUTION_BOUNDARY")
    return {
        "manifest": manifest,
        "identity": identity,
        "experiment": experiment,
        "samples": samples["samples"],
        "approval": approval,
    }


def _current_contexts(repo_root: Path) -> dict[str, Any]:
    repo = repo_root.resolve(strict=True)
    index = HybridSkillSectionIndexV2.load(repo / INDEX_V2, repo / INDEX_V1, repo)
    _full, baseline, resolved = _production_baseline(repo)
    project, provenance, _sources = frozen_project_guidance()
    request = _request(index, resolved, baseline, "character-heavy")
    request = replace(
        request,
        protected_non_skill_prefix=project + "\nSkill instructions (advisory):\n",
        reference_guidance_context=project,
        expected_reference_guidance_sha256=_sha_bytes(project.encode("utf-8")),
    )
    materialized = HybridSkillContextCompilerV1(index).materialize(request)
    treatment = (
        materialized.baseline_context
        + SUPPLEMENT_SEPARATOR
        + materialized.supplement_text
    )
    return {
        "project": project,
        "reference_provenance_sha256": provenance["provenance_manifest_sha256"],
        "control": baseline,
        "treatment": treatment,
        "hybrid_receipt": dict(materialized.receipt),
    }


def _system_prefix() -> str:
    return prior._system_prefix()


def _instruction() -> str:
    return (
        "SLICE1_PHASE_B_EVENT_REALIZATION_SHADOW_V1\n"
        "Generate exactly one non-authoritative shadow candidate for the frozen formal event. "
        "Return only one JSON object with exactly title and narrative. Do not return or modify "
        "Runtime-owned authority, identifiers, order, dependencies, StoryState, Canon, READY, "
        "Draft, Review, or Maintenance. Realize the required obligations through character "
        "choice, resistance, causal change, and bounded sensory specificity."
    )


def reconstruct_sample_input(repo_root: Path, sample_id: str) -> prior.ReconstructedInput:
    repo = repo_root.resolve(strict=True)
    sealed = load_sealed_pilot(repo)
    lock = next(
        (row for row in sealed["samples"] if row["SAMPLE_ID"] == sample_id),
        None,
    )
    _require(lock is not None, "UNKNOWN_SAMPLE")
    contexts = _current_contexts(repo)
    skill = contexts["control"] if lock["ARM"] == "CONTROL" else contexts["treatment"]
    _require(_sha_bytes(skill.encode("utf-8")) == lock["SKILL_CONTEXT_SHA256"],
             "STALE_SKILL_CONTEXT")
    partition = render_pilot_advisory_partition(
        project_guidance=contexts["project"],
        skill_guidance=skill,
        style_guidance="",
        maximum_chars=PILOT_ADVISORY_MAXIMUM_CHARS,
    )
    fixture = _read_json(repo / FIXTURE_PATH)
    system = _system_prefix() + partition.rendered_advisory
    user = json.dumps({
        "contract": prior.current_arm.SLICE1_CONTRACT_IDENTITY,
        "authority": fixture["authority_input"],
        "instruction": _instruction(),
        "expected_output_characters": prior.current_arm.EXPECTED_OUTPUT_CHARACTERS,
        "output_fields": ["title", "narrative"],
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    component = {
        "AUTHORITY_SHA256": lock["AUTHORITY_SHA256"],
        "TASK_SHA256": lock["TASK_SHA256"],
        "STORY_SLICE_SHA256": lock["STORY_SLICE_SHA256"],
        "REFERENCE_GUIDANCE_SHA256": lock["REFERENCE_GUIDANCE_SHA256"],
        "NON_SKILL_PREFIX_SHA256": lock["NON_SKILL_PREFIX_SHA256"],
        "SKILL_CONTEXT_SHA256": lock["SKILL_CONTEXT_SHA256"],
        "OUTPUT_CONTRACT_SHA256": lock["OUTPUT_CONTRACT_SHA256"],
        "VALIDATOR_FINGERPRINT": lock["VALIDATOR_FINGERPRINT"],
        "PROVIDER_MODEL_ROUTE_FINGERPRINT": lock[
            "PROVIDER_MODEL_ROUTE_FINGERPRINT"
        ],
        "SAMPLING_FINGERPRINT": lock["SAMPLING_FINGERPRINT"],
        "OUTPUT_CAP": lock["OUTPUT_CAP"],
        "DESTINATION_ORIGIN": lock["DESTINATION_ORIGIN"],
        "EGRESS_POLICY_SHA256": lock["EGRESS_POLICY_SHA256"],
    }
    _require(_sha_json(component) == lock["MODEL_INPUT_COMPONENT_SHA256"],
             "STALE_INPUT_COMPONENT_BINDING")
    _require(_sha_bytes(system.encode("utf-8")) == lock["SYSTEM_SHA256"],
             "STALE_INPUT_COMPONENT_BINDING")
    _require(_sha_bytes(user.encode("utf-8")) == lock["USER_SHA256"],
             "STALE_INPUT_COMPONENT_BINDING")
    wire_sha = _sha_bytes((system + "\n\0" + user).encode("utf-8"))
    _require(wire_sha == lock["WIRE_INPUT_SHA256"], "STALE_INPUT_COMPONENT_BINDING")
    _require(
        estimate_input_tokens(system + "\n\0" + user) + int(lock["OUTPUT_CAP"])
        <= int(lock["SAFE_CONTEXT_WINDOW_TOKEN_CAP"]),
        "ADVISORY_OVERFLOW",
    )
    return prior.ReconstructedInput(
        pilot_id=sealed["identity"]["PILOT_ID"],
        sample_id=sample_id,
        sample_slot=lock["SAMPLE_SLOT"],
        arm=lock["ARM"],
        system=system,
        user=user,
        system_sha256=lock["SYSTEM_SHA256"],
        user_sha256=lock["USER_SHA256"],
        wire_input_sha256=wire_sha,
        non_skill_prefix_sha256=lock["NON_SKILL_PREFIX_SHA256"],
        non_skill_snapshot_sha256=lock["NON_SKILL_IDENTITY_SHA256"],
        skill_context_sha256=lock["SKILL_CONTEXT_SHA256"],
        model_input_component_binding_sha256=lock["MODEL_INPUT_COMPONENT_SHA256"],
        route_fingerprint=lock["PROVIDER_MODEL_ROUTE_FINGERPRINT"],
        provider_descriptor_sha256=lock["PROVIDER_DESCRIPTOR_SHA256"],
        model_binding_sha256=lock["MODEL_BINDING_SHA256"],
        sampling_policy_sha256=lock["SAMPLING_FINGERPRINT"],
        output_cap=int(lock["OUTPUT_CAP"]),
        validator_sha256=lock["VALIDATOR_FINGERPRINT"],
        advisory_truncation_occurred=partition.truncation_occurred,
        advisory_shedding_occurred=partition.shedding_occurred,
    )


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
    output_cap: int
    transport_policy: Mapping[str, Any]

    async def dispatch(
        self, model_input: prior.ReconstructedInput, attempts: prior.AttemptGuard,
    ) -> str: ...


class HybridFakeDispatcher(prior.FakeDispatcher):
    def __init__(self, repo_root: Path, outcome: str = "SUCCESS") -> None:
        self.offline_fake = True
        self.retry_disabled = True
        self.fallback_disabled = True
        self.route_switch_disabled = True
        self.resume_disabled = True
        state = load_sealed_pilot(repo_root)
        first = state["samples"][0]
        self.route_fingerprint = first["PROVIDER_MODEL_ROUTE_FINGERPRINT"]
        self.provider_descriptor_sha256 = first["PROVIDER_DESCRIPTOR_SHA256"]
        self.model_binding_sha256 = first["MODEL_BINDING_SHA256"]
        self.sampling_policy_sha256 = first["SAMPLING_FINGERPRINT"]
        self.output_cap = int(first["OUTPUT_CAP"])
        self.transport_policy = SingleDispatchTransportPolicyV1.phase_b().definition()
        self.outcome = outcome
        self.attempts = 0


@dataclass
class HybridPilotLedger:
    sample_states: dict[str, str] = field(default_factory=dict)
    stop_condition_fired: bool = False


def fake_permission(lock: Mapping[str, Any], pilot_id: str) -> dict[str, Any]:
    sealed = load_sealed_pilot(Path(__file__).resolve().parents[2])
    return {
        "schema": "HybridOfflineFakePermissionV1",
        "non_executable": True,
        "active_campaign_permission": True,
        "pilot_id": pilot_id,
        "sample_id": lock["SAMPLE_ID"],
        "experiment_lock_sha256": lock["EXPERIMENT_LOCK_SHA256"],
        "successor_head": sealed["approval"]["CURRENT_SUCCESSOR_HEAD"],
        "scopes": list(PERMISSION_SCOPES),
    }


def fake_signed_approval(lock: Mapping[str, Any], pilot_id: str) -> dict[str, Any]:
    return {
        "schema": "HybridOfflineFakeSignedApprovalV1",
        "non_executable": True,
        "approval_id": "offline-hybrid-approval-" + lock["SAMPLE_ID"],
        "pilot_id": pilot_id,
        "sample_id": lock["SAMPLE_ID"],
        "sample_lock_sha256": lock["SAMPLE_LOCK_SHA256"],
        "experiment_lock_sha256": lock["EXPERIMENT_LOCK_SHA256"],
        "model_input_component_binding_sha256": lock["MODEL_INPUT_COMPONENT_SHA256"],
        "route_fingerprint": lock["PROVIDER_MODEL_ROUTE_FINGERPRINT"],
        "destination_origin": lock["DESTINATION_ORIGIN"],
        "egress_policy_sha256": lock["EGRESS_POLICY_SHA256"],
        "wire_input_sha256": lock["WIRE_INPUT_SHA256"],
        "nonce_policy_version": NONCE_POLICY_VERSION,
        "real_dispatcher_version": REAL_DISPATCHER_VERSION,
        "nonce_state": "NOT_CREATED",
        "signed_approval_sha256": _sha_json({
            "kind": "offline-fake", "sample_id": lock["SAMPLE_ID"],
        }),
        "repository_head": "0" * 40,
        "usage_status": "unused",
        "expired": False,
    }


def _validate_dispatcher(
    dispatcher: Dispatcher, model_input: prior.ReconstructedInput,
) -> None:
    _require(dispatcher.route_fingerprint == model_input.route_fingerprint, "WRONG_ROUTE")
    _require(dispatcher.provider_descriptor_sha256 == model_input.provider_descriptor_sha256,
             "WRONG_PROVIDER")
    _require(dispatcher.model_binding_sha256 == model_input.model_binding_sha256,
             "WRONG_MODEL")
    _require(dispatcher.sampling_policy_sha256 == model_input.sampling_policy_sha256,
             "WRONG_SAMPLING_POLICY")
    _require(dispatcher.output_cap == model_input.output_cap, "WRONG_OUTPUT_CAP")
    _require(dispatcher.retry_disabled, "TRANSPORT_RETRY_ATTEMPT")
    _require(dispatcher.fallback_disabled, "FALLBACK_ATTEMPT")
    _require(dispatcher.route_switch_disabled, "ROUTE_SWITCH_ATTEMPT")
    _require(dispatcher.resume_disabled, "RESUME_DISPATCH_ATTEMPT")
    _require(
        dict(dispatcher.transport_policy)
        == SingleDispatchTransportPolicyV1.phase_b().definition(),
        "ADAPTER_AUTO_RETRY_ATTEMPT",
    )


def _eligible(
    samples: list[dict[str, Any]], lock: Mapping[str, Any], ledger: HybridPilotLedger,
) -> None:
    _require(not ledger.stop_condition_fired, "STOP_CONDITION_ALREADY_FIRED")
    _require(lock["SAMPLE_ID"] not in ledger.sample_states, "ALREADY_SEALED_SAMPLE")
    position = SEQUENCE.index(str(lock["SAMPLE_SLOT"]))
    sealed_slots = {
        state.split(":", 1)[0]
        for state in ledger.sample_states.values()
        if state.endswith(":SEALED_VALID")
    }
    for predecessor in SEQUENCE[:position]:
        _require(predecessor in sealed_slots, "LATER_SAMPLE_BEFORE_TURN")


async def launch_one_sealed_hybrid_sample(
    *,
    repo_root: Path,
    pilot_id: str,
    sample_id: str,
    expected_sample_lock_sha256: str,
    expected_experiment_lock_sha256: str,
    permission: Mapping[str, Any] | None,
    signed_approval: Mapping[str, Any] | None,
    nonce_store: prior.NonceStore,
    ledger: HybridPilotLedger,
    dispatcher: Dispatcher,
    output_root: Path,
    offline_fake: bool,
) -> dict[str, Any]:
    sealed = load_sealed_pilot(repo_root)
    current_head = _git(repo_root, "rev-parse", "HEAD")
    _require(
        _git(
            repo_root,
            "merge-base",
            "--is-ancestor",
            str(sealed["approval"]["CURRENT_SUCCESSOR_HEAD"]),
            current_head,
        ) == "",
        "HEAD_OR_WORKTREE_DRIFT",
    )
    _require(
        _git(repo_root, "branch", "--show-current")
        == "r1-ptr3/planning-repair-finding-propagation-20260817",
        "HEAD_OR_WORKTREE_DRIFT",
    )
    if not offline_fake:
        _require(not _git(repo_root, "status", "--porcelain"),
                 "HEAD_OR_WORKTREE_DRIFT")
    _require(pilot_id == sealed["identity"]["PILOT_ID"], "WRONG_PILOT")
    lock = next(
        (row for row in sealed["samples"] if row["SAMPLE_ID"] == sample_id), None,
    )
    _require(lock is not None, "UNKNOWN_SAMPLE")
    _require(lock["SAMPLE_LOCK_SHA256"] == expected_sample_lock_sha256,
             "STALE_SAMPLE_LOCK")
    _require(lock["EXPERIMENT_LOCK_SHA256"] == expected_experiment_lock_sha256,
             "STALE_PARENT_EXPERIMENT_LOCK")
    _eligible(sealed["samples"], lock, ledger)
    _require(bool(permission), "MISSING_CURRENT_CHAT_PERMISSION")
    _require(permission.get("active_campaign_permission") is True,
             "MISSING_CURRENT_CHAT_PERMISSION")
    _require(permission.get("pilot_id") == pilot_id, "PERMISSION_SCOPE_INCOMPLETE")
    _require(permission.get("sample_id") == sample_id, "PERMISSION_SCOPE_INCOMPLETE")
    _require(permission.get("experiment_lock_sha256") == expected_experiment_lock_sha256,
             "PERMISSION_SCOPE_INCOMPLETE")
    _require(
        permission.get("successor_head")
        == sealed["approval"]["CURRENT_SUCCESSOR_HEAD"],
        "PERMISSION_SCOPE_INCOMPLETE",
    )
    _require(set(permission.get("scopes") or ()) == set(PERMISSION_SCOPES),
             "PERMISSION_SCOPE_INCOMPLETE")
    _require(bool(signed_approval), "MISSING_SIGNED_APPROVAL")
    approval = dict(signed_approval or {})
    _require(approval.get("pilot_id") == pilot_id, "STALE_APPROVAL")
    _require(approval.get("sample_id") == sample_id, "APPROVAL_FOR_WRONG_SAMPLE")
    _require(approval.get("sample_lock_sha256") == expected_sample_lock_sha256,
             "APPROVAL_FOR_WRONG_SAMPLE_LOCK")
    _require(approval.get("experiment_lock_sha256") == expected_experiment_lock_sha256,
             "STALE_PARENT_EXPERIMENT_LOCK")
    _require(approval.get("usage_status") == "unused", "APPROVAL_REUSE")
    _require(approval.get("expired") is False, "STALE_APPROVAL")
    _require(approval.get("nonce_state") == "NOT_CREATED",
             "NONCE_CREATED_DURING_APPROVAL")
    if offline_fake:
        _require(permission.get("non_executable") is True,
                 "PERMISSION_SCOPE_INCOMPLETE")
        _require(approval.get("non_executable") is True, "MISSING_SIGNED_APPROVAL")
        _require(dispatcher.offline_fake, "PRODUCTION_CUTOVER_REQUEST")
    else:
        _require(approval.get("repository_head") == current_head,
                 "HEAD_OR_WORKTREE_DRIFT")
    model_input = reconstruct_sample_input(repo_root, sample_id)
    for approval_key, expected in (
        ("model_input_component_binding_sha256", model_input.model_input_component_binding_sha256),
        ("route_fingerprint", model_input.route_fingerprint),
        ("destination_origin", lock["DESTINATION_ORIGIN"]),
        ("egress_policy_sha256", lock["EGRESS_POLICY_SHA256"]),
        ("wire_input_sha256", model_input.wire_input_sha256),
    ):
        _require(approval.get(approval_key) == expected, "STALE_INPUT_COMPONENT_BINDING")
    _validate_dispatcher(dispatcher, model_input)
    reservation = nonce_store.reserve(
        pilot_id=pilot_id,
        sample_id=sample_id,
        sample_lock_sha256=expected_sample_lock_sha256,
        parent_experiment_lock_sha256=expected_experiment_lock_sha256,
        execution_head=str(approval["repository_head"]),
        approval_id=str(approval["approval_id"]),
        signed_approval_sha256=str(approval["signed_approval_sha256"]),
        model_input_component_binding_sha256=model_input.model_input_component_binding_sha256,
        route_fingerprint=model_input.route_fingerprint,
    )
    nonce_binding = {
        "pilot_id": pilot_id,
        "sample_id": sample_id,
        "approval_id": str(approval["approval_id"]),
        "nonce_id": str(reservation["nonce_id"]),
    }
    binder = getattr(dispatcher, "bind_nonce_reservation", None)
    if binder is not None:
        binder(nonce_store=nonce_store, nonce_binding=nonce_binding)
    _require(reconstruct_sample_input(repo_root, sample_id) == model_input,
             "STALE_INPUT_COMPONENT_BINDING")
    nonce_store.mark_dispatch_attempt(**nonce_binding)
    attempts = prior.AttemptGuard()
    attempts.begin_logical_call()
    try:
        raw = await dispatcher.dispatch(model_input, attempts)
        local = prior._terminal_pipeline(repo_root, raw, model_input, output_root)
    except BaseException as exc:
        reason = getattr(exc, "reason_code", "PROVIDER_BOUNDARY_FAILED")
        ledger.sample_states[sample_id] = str(reason)
        ledger.stop_condition_fired = True
        nonce_store.invalidate(
            **nonce_binding, reason=reason, after_dispatch_attempt=True,
        )
        raise
    nonce_store.consume(**nonce_binding)
    ledger.sample_states[sample_id] = f"{lock['SAMPLE_SLOT']}:SEALED_VALID"
    return {
        "status": "SEALED_VALID",
        "sample_id": sample_id,
        "sample_slot": lock["SAMPLE_SLOT"],
        "attempts": attempts.snapshot(),
        "real_boundary_reached": 0 if offline_fake else 1,
        **local,
    }
