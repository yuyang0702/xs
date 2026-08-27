"""Fail-closed orchestration for the five remaining Skill V3 pilot samples.

The module is dormant unless called explicitly.  It derives one bounded user
permission into one JIT signed approval and one durable nonce per sample.  All
active-campaign state lives outside the Git worktree; repository files are
read-only for the complete campaign.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
from typing import Any, Mapping

from novel_flywheel.config import default_settings
from novel_flywheel.runtime_fingerprint_build import (
    CANONICALIZATION_VERSION,
    canonical_json_bytes,
    domain_sha256,
)
from tools.canary import skill_v3_character_heavy_pilot as pilot
from tools.canary import skill_v3_pilot_approval_store as approvals
from tools.canary.skill_v3_a1_destination_binding import (
    DestinationBindingV1,
    resolve_a1_destination_binding_v1,
    validate_destination_authority_v1,
)
from tools.canary.skill_v3_pilot_nonce_store import (
    DurablePilotNonceStoreV1,
    NONCE_POLICY_VERSION,
)
from tools.canary.skill_v3_real_execution_boundary import (
    REAL_DISPATCHER_VERSION,
    canonical_real_execution_environment_v1,
)


CAMPAIGN_POLICY = "SKILL_V3_REMAINING_CAMPAIGN_BOUNDED_USER_PERMISSION_V1"
CAMPAIGN_SEQUENCE = ("B1", "A2", "B2", "A3", "B3")
CAMPAIGN_MAX_ELAPSED_HOURS = 10
CAMPAIGN_MAX_REQUESTS = 5
EXPECTED_DESTINATION = "https://lingsuan.org:443/v1/messages"
EXPECTED_OPERATOR_CLASS = "THIRD_PARTY_RELAY_LOCAL_METADATA_ONLY"
PERMISSION_SCHEMA = "SkillV3RemainingCampaignPermissionReceiptV1"
PERMISSION_DOMAIN = "novel-flywheel-skill-v3-remaining-campaign-permission-v1"
EGRESS_DOMAIN = "novel-flywheel-skill-v3-remaining-sample-egress-policy-v1"
STATE_SCHEMA = "SkillV3RemainingCampaignExternalStateV1"
STATE_DOMAIN = "novel-flywheel-skill-v3-remaining-campaign-state-v1"
RUNTIME_ROOT_RELATIVE = Path(
    "canary-runs/skill-v3-character-heavy-multi-sample-v1/overnight-campaign-v1"
)
B1_SELECTIVE_BINDING = Path(
    "docs/superpowers/reports/skill-v3-character-heavy-pilot-b1-fresh-user-approval-v1/"
    "b1-selective-context-binding-v1.json"
)
B1_PHASE_A_ROOT = B1_SELECTIVE_BINDING.parent
PERMISSION_ROOT_RELATIVE = Path(
    "canary-approval-ledgers/skill-v3-character-heavy-multi-sample-v1/"
    "remaining-campaign-permissions-v1"
)
STOP_REASONS = {
    "BLOCKED_PRE_DISPATCH", "SEALED_INVALID", "GIT_DRIFT",
    "SAMPLE_LOCK_DRIFT", "MODEL_INPUT_DRIFT", "WIRE_INPUT_DRIFT",
    "SKILL_SOURCE_DRIFT", "REFERENCE_DISTILL_DRIFT", "ROUTE_DRIFT",
    "DESTINATION_DRIFT", "EGRESS_POLICY_DRIFT", "APPROVAL_FAILURE",
    "NONCE_FAILURE", "CREDENTIAL_FAILURE", "PROVIDER_CLIENT_FAILURE",
    "NETWORK_HTTP_TRANSPORT_FAILURE", "ATTEMPT_COUNTER_VIOLATION",
    "PARSE_FAILURE", "SCHEMA_FAILURE", "DOMAIN_VALIDATION_FAILURE",
    "LOCAL_VALIDATION_FAILURE", "TERMINAL_PIPELINE_FAILURE",
    "PRIVACY_VIOLATION", "CAMPAIGN_REQUEST_BUDGET_EXHAUSTED",
    "CAMPAIGN_ELAPSED_CAP_REACHED", "METHOD_CONTAMINATION",
}


class SkillV3OvernightCampaignError(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


def _require(condition: bool, reason_code: str) -> None:
    if not condition:
        raise SkillV3OvernightCampaignError(reason_code)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z",
    )


def _parse_utc(value: Any) -> datetime:
    _require(isinstance(value, str) and value.endswith("Z"), "CAMPAIGN_TIME_INVALID")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(timezone.utc)
    except ValueError as exc:
        raise SkillV3OvernightCampaignError("CAMPAIGN_TIME_INVALID") from exc


def _git(repo_root: Path, *args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=repo_root, check=True, capture_output=True, text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SkillV3OvernightCampaignError("GIT_DRIFT") from exc


def clean_git_identity(repo_root: Path) -> tuple[str, str]:
    repo = repo_root.resolve(strict=True)
    head = _git(repo, "rev-parse", "HEAD")
    branch = _git(repo, "branch", "--show-current")
    _require(not _git(repo, "status", "--porcelain=v1", "-uall"), "GIT_DRIFT")
    return head, branch


def git_identity(repo_root: Path) -> tuple[str, str]:
    repo = repo_root.resolve(strict=True)
    return _git(repo, "rev-parse", "HEAD"), _git(repo, "branch", "--show-current")


def _outside_worktree(repo_root: Path, path: Path) -> Path:
    repo = repo_root.resolve(strict=True)
    requested = Path(os.path.abspath(path))
    try:
        requested.relative_to(repo)
    except ValueError:
        pass
    else:
        raise SkillV3OvernightCampaignError("ACTIVE_CAMPAIGN_REPO_WRITE_FORBIDDEN")
    requested.mkdir(parents=True, exist_ok=True)
    resolved = requested.resolve(strict=True)
    _require(
        os.path.normcase(str(resolved)) == os.path.normcase(str(requested)),
        "EXTERNAL_STORE_PATH_NOT_EXACT",
    )
    for component in (resolved, *resolved.parents):
        attributes = getattr(component.stat(), "st_file_attributes", 0)
        _require(not attributes & 0x400, "EXTERNAL_STORE_REPARSE_POINT_FORBIDDEN")
        if component.parent == component:
            break
    return resolved


def _exclusive_json(path: Path, value: Mapping[str, Any]) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise SkillV3OvernightCampaignError("CAMPAIGN_REUSE_OR_RESUME_FORBIDDEN") from exc
    try:
        os.write(descriptor, canonical_json_bytes(value) + b"\n")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    _exclusive_json(temporary, value)
    os.replace(temporary, path)


def remaining_locks(repo_root: Path) -> tuple[dict[str, Any], ...]:
    sealed = pilot.load_sealed_pilot(repo_root)
    rows = tuple(
        dict(next(row for row in sealed["locks"] if row["sample_slot"] == slot))
        for slot in CAMPAIGN_SEQUENCE
    )
    _require(tuple(row["sample_slot"] for row in rows) == CAMPAIGN_SEQUENCE, "SAMPLE_LOCK_DRIFT")
    return rows


def validate_a1_sealed_valid_evidence(repo_root: Path) -> dict[str, Any]:
    root = repo_root.resolve(strict=True) / B1_PHASE_A_ROOT
    manifest = json.loads(
        (root / "sha256-manifest-phase-a-v1.json").read_text(encoding="utf-8")
    )
    _require(manifest.get("status") == "EXACT", "A1_SEALED_VALID_EVIDENCE_DRIFT")
    for entry in manifest.get("entries") or ():
        path = root / str(entry.get("path") or "")
        _require(path.is_file(), "A1_SEALED_VALID_EVIDENCE_DRIFT")
        data = path.read_bytes()
        _require(len(data) == entry.get("bytes"), "A1_SEALED_VALID_EVIDENCE_DRIFT")
        _require(
            hashlib.sha256(data).hexdigest() == entry.get("sha256"),
            "A1_SEALED_VALID_EVIDENCE_DRIFT",
        )
    value = json.loads(
        (root / "a1-valid-sample-binding-v1.json").read_text(encoding="utf-8")
    )
    sealed = pilot.load_sealed_pilot(repo_root)
    lock = next(row for row in sealed["locks"] if row["sample_slot"] == "A1")
    checks = (
        value.get("status") == "PASS",
        value.get("pilot_id") == pilot.PILOT_ID,
        value.get("sample_id") == lock["sample_id"],
        value.get("sample_validity") == "SEALED_VALID",
        value.get("approval_final_state") == "CONSUMED",
        value.get("nonce_final_state") == "CONSUMED",
        value.get("provider_request_attempt_count") == 1,
        all(
            value.get(field) == 0
            for field in (
                "retry_count", "transport_retry_count", "fallback_count",
                "route_switch_count", "resume_dispatch_count", "second_dispatch_count",
            )
        ),
        value.get("counts_as_valid_pilot_sample") is True,
    )
    _require(all(checks), "A1_SEALED_VALID_EVIDENCE_DRIFT")
    return value


def remaining_sample_egress_policy_v1(
    repo_root: Path, sample_id: str,
) -> dict[str, Any]:
    repo = repo_root.resolve(strict=True)
    lock = next(
        (row for row in remaining_locks(repo) if row["sample_id"] == sample_id),
        None,
    )
    _require(lock is not None, "SAMPLE_LOCK_DRIFT")
    model_input = pilot.reconstruct_sample_input(repo, sample_id)
    arm_component = f"{model_input.arm}_ARM_SKILL_CONTEXT"
    components = [
        ("SYSTEM_CONTEXT", model_input.system_sha256, "PROJECT_CONTENT"),
        ("TASK_ENVELOPE", lock["task_sha256"], "OPERATIONAL_METADATA"),
        ("AUTHORITY_CONTEXT", lock["authority_sha256"], "PROJECT_CONTENT"),
        ("STORY_SLICE", lock["story_slice_sha256"], "PROJECT_CONTENT"),
        ("NON_SKILL_PROJECT_GUIDANCE", lock["project_guidance_sha256"], "CREATIVE_GUIDANCE"),
        (arm_component, model_input.skill_context_sha256, "CREATIVE_GUIDANCE"),
        ("OUTPUT_CONTRACT", lock["output_contract_sha256"], "OPERATIONAL_METADATA"),
        (
            "PROVIDER_REQUEST_METADATA",
            domain_sha256(
                "novel-flywheel-skill-v3-remaining-provider-request-metadata-v1",
                {
                    "provider": model_input.provider_descriptor_sha256,
                    "model": model_input.model_binding_sha256,
                    "route": model_input.route_fingerprint,
                    "output_cap": model_input.output_cap,
                },
            ),
            "OPERATIONAL_METADATA",
        ),
    ]
    body = {
        "schema": "SkillV3RemainingSampleEgressPolicyV1",
        "version": 1,
        "sample_id": sample_id,
        "sample_slot": model_input.sample_slot,
        "wire_input_sha256": model_input.wire_input_sha256,
        "components": [
            {
                "component": name,
                "egress_included": True,
                "source_identity_or_sha": identity,
                "sensitivity_class": sensitivity,
            }
            for name, identity, sensitivity in components
        ],
        "excluded": {
            "raw_ref_corpus_egress": False,
            "raw_distill_evidence_excerpt_egress": False,
            "learn_node_raw_evidence_egress": False,
            "prior_sample_prose_egress": False,
            "prior_sample_result_egress": False,
            "historical_blind_result_egress": False,
            "credential_egress": False,
            "local_absolute_path_egress": False,
        },
    }
    return {**body, "egress_policy_sha256": domain_sha256(EGRESS_DOMAIN, body)}


def resolve_remaining_destinations_v1(
    repo_root: Path, route_database: Path,
) -> dict[str, DestinationBindingV1]:
    destination = resolve_a1_destination_binding_v1(
        repo_root=repo_root, route_database=route_database,
    )
    _require(
        f"{destination.origin}:{destination.port}{destination.api_path}"
        == EXPECTED_DESTINATION,
        "DESTINATION_DRIFT",
    )
    _require(destination.operator_class == EXPECTED_OPERATOR_CLASS, "DESTINATION_DRIFT")
    bindings: dict[str, DestinationBindingV1] = {}
    for lock in remaining_locks(repo_root):
        model_input = pilot.reconstruct_sample_input(repo_root, str(lock["sample_id"]))
        _require(model_input.route_fingerprint == destination.route_fingerprint, "ROUTE_DRIFT")
        _require(
            model_input.provider_descriptor_sha256 == destination.provider_descriptor_sha256,
            "ROUTE_DRIFT",
        )
        _require(model_input.model_binding_sha256 == destination.model_binding_sha256, "ROUTE_DRIFT")
        bindings[str(lock["sample_id"])] = destination
    _require(len({item.origin for item in bindings.values()}) == 1, "DESTINATION_DRIFT")
    return bindings


def authorization_sentence(repo_root: Path) -> str:
    head, _branch = clean_git_identity(repo_root)
    ids = [str(row["sample_id"]) for row in remaining_locks(repo_root)]
    return (
        f"我明确授权基于 successor HEAD {head} 和 parent lock "
        f"{pilot.PARENT_EXPERIMENT_LOCK_SHA256}，按 B1→A2→B2→A3→B3 顺序仅执行已封存样本 "
        f"{', '.join(ids)}；每个样本仅可向 {EXPECTED_DESTINATION}（{EXPECTED_OPERATOR_CLASS}）"
        "外发其自身已封存请求所需的 system/context、task、authority、story slice、非 Skill 项目 guidance、"
        "对应 arm Skill context、output contract 与 Provider request metadata，并允许必要的凭据读取、网络访问和付费 Provider/模型调用；"
        "剩余批次最多 5 次付费请求、每样本最多 1 次，我接受未封存 USD/CNY 上限下这最多 5 次请求的实际费用风险；"
        "每个样本仍须在执行前创建独立 JIT signed approval 和独立 durable nonce；不授权 retry、transport retry、fallback、route switch、resume、second dispatch、"
        "alternate destination、cross-origin redirect、replacement sample、Skill V3 cutover、Planning V2 cutover 或 Full Short；"
        "任一 blocked、invalid、failure 或 drift 立即停止，授权在批次完成、首个停止条件或开始后 10 小时三者最先发生时失效。"
    )


def default_permission_store_root() -> Path:
    return default_settings().data_dir / PERMISSION_ROOT_RELATIVE


def default_campaign_runtime_root() -> Path:
    return default_settings().data_dir / RUNTIME_ROOT_RELATIVE


def create_campaign_permission_receipt_v1(
    *, repo_root: Path, authorization_message: str,
    authorization_context_identity_sha256: str,
    store_root: Path | None = None, now: datetime | None = None,
) -> dict[str, Any]:
    """Create the non-executable campaign permission after exact user consent."""

    repo = repo_root.resolve(strict=True)
    head, branch = clean_git_identity(repo)
    _require(authorization_message == authorization_sentence(repo), "CAMPAIGN_PERMISSION_TEXT_MISMATCH")
    _require(
        re.fullmatch(r"[0-9a-f]{64}", authorization_context_identity_sha256) is not None,
        "CAMPAIGN_PERMISSION_CONTEXT_INVALID",
    )
    issued = now or _utc_now()
    expires = issued + timedelta(hours=CAMPAIGN_MAX_ELAPSED_HOURS)
    auth_sha = hashlib.sha256(authorization_message.encode("utf-8")).hexdigest()
    rows = remaining_locks(repo)
    body = {
        "schema": PERMISSION_SCHEMA,
        "version": 1,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "policy": CAMPAIGN_POLICY,
        "repository_head": head,
        "repository_branch": branch,
        "pilot_id": pilot.PILOT_ID,
        "parent_experiment_lock_sha256": pilot.PARENT_EXPERIMENT_LOCK_SHA256,
        "authorized_sequence": list(CAMPAIGN_SEQUENCE),
        "authorized_sample_ids": [str(row["sample_id"]) for row in rows],
        "destination": EXPECTED_DESTINATION,
        "destination_operator_class": EXPECTED_OPERATOR_CLASS,
        "max_remaining_provider_requests": CAMPAIGN_MAX_REQUESTS,
        "max_per_sample_provider_requests": 1,
        "max_elapsed_hours": CAMPAIGN_MAX_ELAPSED_HOURS,
        "remaining_cost_cap": "UNKNOWN_NOT_SEALED",
        "actual_fee_risk_accepted": True,
        "stop_on_first_failure": True,
        "no_retry": True,
        "no_transport_retry": True,
        "no_fallback": True,
        "no_route_switch": True,
        "no_resume": True,
        "no_second_dispatch": True,
        "no_alternate_destination": True,
        "no_cross_origin_redirect": True,
        "no_replacement_sample": True,
        "skill_v3_cutover_authorized": False,
        "planning_v2_cutover_authorized": False,
        "full_short_authorized": False,
        "authorization_message_sha256": auth_sha,
        "authorization_context_identity_sha256": authorization_context_identity_sha256,
        "issued_at": _utc_text(issued),
        "expires_at": _utc_text(expires),
        "usage_status": "unused",
        "executable_signed_approval": False,
    }
    receipt = {**body, "campaign_authorization_sha256": domain_sha256(PERMISSION_DOMAIN, body)}
    root = _outside_worktree(repo, store_root or default_permission_store_root())
    _exclusive_json(root / f"{receipt['campaign_authorization_sha256']}.permission.json", receipt)
    _require(clean_git_identity(repo) == (head, branch), "GIT_DRIFT")
    return receipt


def validate_campaign_permission_receipt_v1(
    *, repo_root: Path, receipt: Mapping[str, Any], now: datetime | None = None,
) -> dict[str, Any]:
    head, branch = clean_git_identity(repo_root)
    body = dict(receipt)
    digest = body.pop("campaign_authorization_sha256", None)
    _require(digest == domain_sha256(PERMISSION_DOMAIN, body), "CAMPAIGN_PERMISSION_SHA_MISMATCH")
    _require(receipt.get("schema") == PERMISSION_SCHEMA, "CAMPAIGN_PERMISSION_SCHEMA_MISMATCH")
    _require(receipt.get("policy") == CAMPAIGN_POLICY, "CAMPAIGN_PERMISSION_SCOPE_MISMATCH")
    _require(receipt.get("pilot_id") == pilot.PILOT_ID, "CAMPAIGN_PERMISSION_SCOPE_MISMATCH")
    _require(
        receipt.get("parent_experiment_lock_sha256") == pilot.PARENT_EXPERIMENT_LOCK_SHA256,
        "CAMPAIGN_PERMISSION_SCOPE_MISMATCH",
    )
    _require(receipt.get("repository_head") == head, "GIT_DRIFT")
    _require(receipt.get("repository_branch") == branch, "GIT_DRIFT")
    _require(tuple(receipt.get("authorized_sequence") or ()) == CAMPAIGN_SEQUENCE, "CAMPAIGN_PERMISSION_SCOPE_MISMATCH")
    _require(
        tuple(receipt.get("authorized_sample_ids") or ())
        == tuple(str(row["sample_id"]) for row in remaining_locks(repo_root)),
        "CAMPAIGN_PERMISSION_SCOPE_MISMATCH",
    )
    _require(receipt.get("destination") == EXPECTED_DESTINATION, "DESTINATION_DRIFT")
    _require(receipt.get("destination_operator_class") == EXPECTED_OPERATOR_CLASS, "DESTINATION_DRIFT")
    _require(receipt.get("max_remaining_provider_requests") == 5, "CAMPAIGN_REQUEST_BUDGET_EXHAUSTED")
    _require(receipt.get("max_per_sample_provider_requests") == 1, "CAMPAIGN_REQUEST_BUDGET_EXHAUSTED")
    _require(receipt.get("max_elapsed_hours") == 10, "CAMPAIGN_ELAPSED_CAP_REACHED")
    _require(receipt.get("remaining_cost_cap") == "UNKNOWN_NOT_SEALED", "CAMPAIGN_PERMISSION_SCOPE_MISMATCH")
    _require(receipt.get("actual_fee_risk_accepted") is True, "CAMPAIGN_PERMISSION_SCOPE_MISMATCH")
    _require(receipt.get("usage_status") == "unused", "CAMPAIGN_REUSE_OR_RESUME_FORBIDDEN")
    _require(
        receipt.get("authorization_message_sha256")
        == hashlib.sha256(authorization_sentence(repo_root).encode("utf-8")).hexdigest(),
        "CAMPAIGN_PERMISSION_TEXT_MISMATCH",
    )
    for field in (
        "stop_on_first_failure", "no_retry", "no_transport_retry", "no_fallback",
        "no_route_switch", "no_resume", "no_second_dispatch",
        "no_alternate_destination", "no_cross_origin_redirect", "no_replacement_sample",
    ):
        _require(receipt.get(field) is True, "CAMPAIGN_PERMISSION_SCOPE_MISMATCH")
    _require(
        all(receipt.get(field) is False for field in (
            "skill_v3_cutover_authorized", "planning_v2_cutover_authorized",
            "full_short_authorized", "executable_signed_approval",
        )),
        "CAMPAIGN_PERMISSION_SCOPE_MISMATCH",
    )
    current = now or _utc_now()
    issued = _parse_utc(receipt.get("issued_at"))
    expires = _parse_utc(receipt.get("expires_at"))
    _require(expires - issued == timedelta(hours=10), "CAMPAIGN_TIME_INVALID")
    _require(issued <= current <= expires, "CAMPAIGN_ELAPSED_CAP_REACHED")
    return dict(receipt)


def load_campaign_permission_receipt_v1(
    *, repo_root: Path, campaign_authorization_sha256: str,
    store_root: Path | None = None, now: datetime | None = None,
) -> dict[str, Any]:
    root = _outside_worktree(repo_root, store_root or default_permission_store_root())
    try:
        value = json.loads((root / f"{campaign_authorization_sha256}.permission.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SkillV3OvernightCampaignError("CAMPAIGN_PERMISSION_NOT_FOUND") from exc
    _require(isinstance(value, dict), "CAMPAIGN_PERMISSION_NOT_FOUND")
    return validate_campaign_permission_receipt_v1(repo_root=repo_root, receipt=value, now=now)


def _jit_payload(
    *, repo_root: Path, lock: Mapping[str, Any], permission: Mapping[str, Any],
    destination: DestinationBindingV1, approval_id: str, now: datetime,
) -> dict[str, Any]:
    head, _branch = clean_git_identity(repo_root)
    model_input = pilot.reconstruct_sample_input(repo_root, str(lock["sample_id"]))
    egress = remaining_sample_egress_policy_v1(repo_root, str(lock["sample_id"]))
    expires = min(now + timedelta(hours=2), _parse_utc(permission["expires_at"]))
    return {
        "approval_id": approval_id,
        "repository_head": head,
        "pilot_id": pilot.PILOT_ID,
        "sample_id": lock["sample_id"],
        "sample_slot": lock["sample_slot"],
        "arm": lock["arm"],
        "sample_index": int(lock["sample_index"]),
        "sample_lock_sha256": lock["sample_lock_sha256"],
        "parent_experiment_lock_sha256": pilot.PARENT_EXPERIMENT_LOCK_SHA256,
        "model_input_component_binding_sha256": model_input.model_input_component_binding_sha256,
        "provider_descriptor_sha256": model_input.provider_descriptor_sha256,
        "model_binding_sha256": model_input.model_binding_sha256,
        "route_fingerprint": model_input.route_fingerprint,
        "max_output_tokens": model_input.output_cap,
        "user_authorization_message_sha256": permission["authorization_message_sha256"],
        "user_authorization_context_identity_sha256": permission["authorization_context_identity_sha256"],
        "issued_at": _utc_text(now),
        "expires_at": _utc_text(expires),
        "wire_input_sha256": model_input.wire_input_sha256,
        "sampling_policy_sha256": model_input.sampling_policy_sha256,
        "validator_sha256": model_input.validator_sha256,
        "nonce_policy_version": NONCE_POLICY_VERSION,
        "real_dispatcher_version": REAL_DISPATCHER_VERSION,
        "destination_origin": destination.origin,
        "destination_origin_sha256": destination.destination_origin_sha256,
        "destination_path_or_prefix": destination.api_path,
        "destination_operator_class": destination.operator_class,
        "egress_policy_sha256": egress["egress_policy_sha256"],
        "cross_origin_redirect_allowed": False,
        "unbound_proxy_route_allowed": False,
        "campaign_authorization_sha256": permission["campaign_authorization_sha256"],
        "campaign_authorization_context_identity_sha256": permission["authorization_context_identity_sha256"],
        "campaign_expires_at": permission["expires_at"],
    }


class RemainingCampaignNonceAdapter:
    def __init__(
        self, *, delegate: DurablePilotNonceStoreV1,
        destination: DestinationBindingV1, approval: Mapping[str, Any],
    ) -> None:
        self.delegate = delegate
        self.destination = destination
        self.approval = dict(approval)
        validate_destination_authority_v1(
            self.approval,
            destination=destination,
            egress_policy_sha256=str(self.approval["egress_policy_sha256"]),
        )

    def reserve(self, **bindings: Any) -> Mapping[str, Any]:
        _require(
            bindings.get("signed_approval_sha256") == self.approval.get("signed_approval_sha256"),
            "NONCE_FAILURE",
        )
        return self.delegate.reserve_destination_bound_v2(
            **bindings,
            approved_destination_origin=self.destination.origin,
            approved_destination_origin_sha256=self.destination.destination_origin_sha256,
            approved_destination_path_or_prefix=self.destination.api_path,
            egress_policy_sha256=str(self.approval["egress_policy_sha256"]),
            cross_origin_redirect_allowed=False,
            unbound_proxy_route_allowed=False,
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self.delegate, name)


def _sealed_state(body: Mapping[str, Any]) -> dict[str, Any]:
    return {**dict(body), "state_sha256": domain_sha256(STATE_DOMAIN, body)}


async def run_remaining_campaign_once(
    *, repo_root: Path, campaign_authorization_sha256: str,
) -> dict[str, Any]:
    """Execute B1,A2,B2,A3,B3 once; never resume an existing campaign state."""

    repo = repo_root.resolve(strict=True)
    head, branch = clean_git_identity(repo)
    permission = load_campaign_permission_receipt_v1(
        repo_root=repo,
        campaign_authorization_sha256=campaign_authorization_sha256,
    )
    validate_a1_sealed_valid_evidence(repo)
    environment = canonical_real_execution_environment_v1(repo)
    destinations = resolve_remaining_destinations_v1(repo, environment.route_database)
    runtime_root = _outside_worktree(repo, default_campaign_runtime_root())
    campaign_root = runtime_root / campaign_authorization_sha256
    campaign_root.mkdir(parents=True, exist_ok=False)
    state_path = campaign_root / "campaign-state-v1.json"
    started = _utc_now()
    state: dict[str, Any] = {
        "schema": STATE_SCHEMA,
        "version": 1,
        "repository_head": head,
        "repository_branch": branch,
        "campaign_authorization_sha256": campaign_authorization_sha256,
        "started_at": _utc_text(started),
        "status": "ACTIVE",
        "sample_results": [],
        "cumulative_provider_attempts": 0,
        "cumulative_http_post_attempts": 0,
        "cumulative_network_attempts": 0,
        "stop_reason": None,
    }
    _exclusive_json(state_path, _sealed_state(state))
    sealed = pilot.load_sealed_pilot(repo)
    a1 = next(row for row in sealed["locks"] if row["sample_slot"] == "A1")
    ledger = pilot.FakePilotLedger(
        sample_states={str(a1["sample_id"]): "A1:SEALED_VALID"},
    )
    try:
        for lock in remaining_locks(repo):
            if _utc_now() > _parse_utc(permission["expires_at"]):
                raise SkillV3OvernightCampaignError("CAMPAIGN_ELAPSED_CAP_REACHED")
            _require(int(state["cumulative_provider_attempts"]) < 5, "CAMPAIGN_REQUEST_BUDGET_EXHAUSTED")
            _require(clean_git_identity(repo) == (head, branch), "GIT_DRIFT")
            sample_id = str(lock["sample_id"])
            destination = destinations[sample_id]
            approval_id = f"sv3o-{lock['sample_slot'].lower()}-{secrets.token_hex(12)}"
            now = _utc_now()
            payload = _jit_payload(
                repo_root=repo, lock=lock, permission=permission,
                destination=destination, approval_id=approval_id, now=now,
            )
            approval = approvals.create_remaining_campaign_signed_approval_v4(
                repo_root=repo,
                store_root=environment.approval_store_root,
                payload=payload,
                now=now,
            )
            destination_authority = {
                field: approval[field]
                for field in (
                    "destination_origin", "destination_origin_sha256",
                    "destination_path_or_prefix", "destination_operator_class",
                    "egress_policy_sha256", "cross_origin_redirect_allowed",
                    "unbound_proxy_route_allowed",
                )
            }
            dispatcher = environment.dispatcher_for(
                approval_id,
                approved_destination_authority=destination_authority,
            )
            nonce_store = RemainingCampaignNonceAdapter(
                delegate=environment.nonce_store(),
                destination=destination,
                approval=approval,
            )
            per_sample_permission = {
                "pilot_id": pilot.PILOT_ID,
                "sample_id": sample_id,
                "scopes": list(pilot.PERMISSION_SCOPES),
                "campaign_authorization_sha256": campaign_authorization_sha256,
            }
            output_root = dispatcher.execution_root / "output"
            try:
                result = await pilot.launch_one_sealed_sample(
                    repo_root=repo,
                    pilot_id=pilot.PILOT_ID,
                    sample_id=sample_id,
                    expected_sample_lock_sha256=str(lock["sample_lock_sha256"]),
                    expected_parent_experiment_lock_sha256=pilot.PARENT_EXPERIMENT_LOCK_SHA256,
                    permission=per_sample_permission,
                    signed_approval=approval,
                    nonce_store=nonce_store,
                    ledger=ledger,
                    dispatcher=dispatcher,
                    output_root=output_root,
                    offline_fake=False,
                )
            except BaseException as exc:
                reason = str(getattr(exc, "reason_code", "TERMINAL_PIPELINE_FAILURE"))
                receipt_sha = domain_sha256(
                    "novel-flywheel-skill-v3-remaining-sample-failure-v1",
                    {"sample_id": sample_id, "reason": reason},
                )
                approvals.consume_successor_signed_approval_v1(
                    store_root=environment.approval_store_root,
                    approval_id=approval_id,
                    execution_receipt_sha256=receipt_sha,
                )
                transport = dispatcher.transport_attempt_snapshot()
                state["sample_results"].append({
                    "sample_id": sample_id,
                    "sample_slot": lock["sample_slot"],
                    "status": "STOPPED",
                    "reason": reason,
                    "approval_id": approval_id,
                    "signed_approval_sha256": approval["signed_approval_sha256"],
                    "transport_attempts": transport,
                })
                state["cumulative_provider_attempts"] += int(transport.get("real_provider_request_attempts", 0))
                state["cumulative_http_post_attempts"] += int(transport.get("http_post_attempts", 0))
                state["cumulative_network_attempts"] += int(transport.get("network_request_attempts", 0))
                state["status"] = "STOPPED"
                state["stop_reason"] = reason
                break
            receipt_sha = domain_sha256(
                "novel-flywheel-skill-v3-remaining-sample-success-v1", result,
            )
            approvals.consume_successor_signed_approval_v1(
                store_root=environment.approval_store_root,
                approval_id=approval_id,
                execution_receipt_sha256=receipt_sha,
            )
            transport = dispatcher.transport_attempt_snapshot()
            state["sample_results"].append({
                "sample_id": sample_id,
                "sample_slot": lock["sample_slot"],
                "status": "SEALED_VALID",
                "approval_id": approval_id,
                "signed_approval_sha256": approval["signed_approval_sha256"],
                "execution_receipt_sha256": receipt_sha,
                "artifact_file_sha256": result["artifact_file_sha256"],
                "attempts": result["attempts"],
                "transport_attempts": transport,
            })
            state["cumulative_provider_attempts"] += int(transport.get("real_provider_request_attempts", 0))
            state["cumulative_http_post_attempts"] += int(transport.get("http_post_attempts", 0))
            state["cumulative_network_attempts"] += int(transport.get("network_request_attempts", 0))
            _require(state["cumulative_provider_attempts"] <= 5, "ATTEMPT_COUNTER_VIOLATION")
            _require(state["cumulative_http_post_attempts"] <= 5, "ATTEMPT_COUNTER_VIOLATION")
            _require(state["cumulative_network_attempts"] <= 5, "ATTEMPT_COUNTER_VIOLATION")
            _atomic_json(state_path, _sealed_state(state))
        if state["status"] == "ACTIVE":
            state["status"] = "SEALED_VALID"
    except BaseException as exc:
        state["status"] = "STOPPED"
        state["stop_reason"] = str(getattr(exc, "reason_code", "BLOCKED_PRE_DISPATCH"))
    state["finished_at"] = _utc_text(_utc_now())
    _require(clean_git_identity(repo) == (head, branch), "GIT_DRIFT")
    final = _sealed_state(state)
    _atomic_json(state_path, final)
    return final


def phase_a_snapshot(repo_root: Path) -> dict[str, Any]:
    """Build the complete metadata-only Phase-A binding; no external actions."""

    repo = repo_root.resolve(strict=True)
    head, branch = git_identity(repo)
    a1_evidence = validate_a1_sealed_valid_evidence(repo)
    environment = canonical_real_execution_environment_v1(repo)
    destinations = resolve_remaining_destinations_v1(repo, environment.route_database)
    sealed = pilot.load_sealed_pilot(repo)
    selective = json.loads((repo / B1_SELECTIVE_BINDING).read_text(encoding="utf-8"))
    _require(selective.get("status") == "PASS", "SKILL_SOURCE_DRIFT")
    rows = []
    for lock in remaining_locks(repo):
        sample_id = str(lock["sample_id"])
        model_input = pilot.reconstruct_sample_input(repo, sample_id)
        row = dict(lock)
        row.update({
            "wire_input_sha256": model_input.wire_input_sha256,
            "system_sha256": model_input.system_sha256,
            "user_sha256": model_input.user_sha256,
            "non_skill_snapshot_sha256": model_input.non_skill_snapshot_sha256,
            "non_skill_guidance_snapshot_sha256": model_input.non_skill_snapshot_sha256,
            "destination": asdict(destinations[sample_id]),
            "egress_policy": remaining_sample_egress_policy_v1(repo, sample_id),
            "nonce_policy_version": NONCE_POLICY_VERSION,
            "real_dispatcher_version": REAL_DISPATCHER_VERSION,
        })
        if row["arm"] == "B":
            _require(
                selective.get("skill_context_sha256") == row["skill_context_sha256"],
                "SKILL_SOURCE_DRIFT",
            )
            row.update({
                "selective_compiler_version": selective["compiler_version"],
                "selected_section_ids": list(selective["selected_section_ids"]),
                "selected_section_content_shas": dict(
                    selective["selected_section_content_shas"],
                ),
                "rendered_skill_context_sha256": selective["skill_context_sha256"],
                "rendered_skill_context_chars": selective["rendered_skill_context_chars"],
                "skill_token_estimate": selective["skill_context_token_estimate"],
            })
        rows.append(row)
    a1 = next(row for row in sealed["locks"] if row["sample_slot"] == "A1")
    a1_input = pilot.reconstruct_sample_input(repo, str(a1["sample_id"]))
    non_skill_values = {
        (
            row["authority_sha256"], row["task_sha256"], row["story_slice_sha256"],
            row["non_skill_prompt_sha256"], row["project_guidance_sha256"],
            row["reference_derived_provenance_sha256"], row["output_contract_sha256"],
            row["validator_sha256"], row["ptr_policy_sha256"],
        )
        for row in sealed["locks"]
    }
    _require(len(non_skill_values) == 1, "METHOD_CONTAMINATION")
    return {
        "status": "EXACT",
        "policy": CAMPAIGN_POLICY,
        "repository_head": head,
        "repository_branch": branch,
        "pilot_id": pilot.PILOT_ID,
        "parent_experiment_lock_sha256": pilot.PARENT_EXPERIMENT_LOCK_SHA256,
        "a1": {
            **dict(a1),
            "wire_input_sha256": a1_input.wire_input_sha256,
            "required_state": "SEALED_VALID",
            "provider_request_count": 1,
            "sealed_valid_evidence_status": a1_evidence["status"],
        },
        "remaining": rows,
        "sequence": list(CAMPAIGN_SEQUENCE),
        "all_non_skill_model_visible_bytes_identical_across_6": True,
        "primary_changed_variable": "SKILL_CONTEXT",
        "uncontrolled_variable_count": 0,
        "contamination": {
            "prior_sample_prose_in_input": False,
            "prior_sample_result_in_input": False,
            "prior_sample_execution_metadata_in_model_input": False,
            "prior_sample_blind_result_in_input": False,
            "cross_arm_prose_injection": False,
        },
        "remaining_max_output_tokens_sum": sum(int(row["output_cap"]) for row in rows),
        "remaining_max_provider_requests": 5,
        "remaining_max_network_attempts": 5,
        "remaining_cost_cap": "UNKNOWN_NOT_SEALED",
        "external_actions": {
            "real_nonce_created": 0,
            "credential_lookup_count": 0,
            "network_calls": 0,
            "model_calls": 0,
            "paid_calls": 0,
        },
    }
