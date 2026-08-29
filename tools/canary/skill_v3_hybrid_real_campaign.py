"""Closed-world, durable execution boundary for the sealed Hybrid campaign.

The module owns no literary policy and never changes the six sealed model
inputs.  It composes the already sealed single-sample approval, nonce,
dispatcher, and terminal-pipeline seams into one restart-safe campaign.  Tests
may replace only the lowest HTTP client boundary; such runs remain explicitly
non-executable and their artifacts are permanently marked dry-run-only.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import secrets
from typing import Any, Callable, Mapping, Sequence

from novel_flywheel.config import default_settings
from novel_flywheel.runtime_fingerprint_build import (
    CANONICALIZATION_VERSION,
    canonical_json_bytes,
    domain_sha256,
)
from tools.canary import skill_v3_hybrid_character_heavy_pilot as hybrid
from tools.canary.skill_v3_hybrid_campaign import HybridApprovalBoundNonceAdapter
from tools.canary.skill_v3_hybrid_jit_approval import (
    DurableHybridApprovalStoreV1,
    HybridJitApprovalError,
    ZERO_ATTEMPT_COUNTERS,
    _FileLock,
    _atomic_replace,
    _outside_store,
    _read_json,
    _write_exclusive,
    campaign_permission_body_from_sealed,
    create_one_hybrid_sample_jit_approval,
    current_git_identity,
    default_hybrid_approval_store_root,
    seal_campaign_permission_v1,
    validate_approval_domain_v1,
    validate_campaign_permission_v1,
)
from tools.canary.skill_v3_pilot_nonce_store import (
    DurablePilotNonceStoreV1,
    default_nonce_store_root,
)
from tools.canary.skill_v3_a1_destination_binding import (
    resolve_a1_destination_binding_v1,
)
from tools.canary.skill_v3_real_execution_boundary import RealPilotDispatcherV1


AUTHORIZATION_TITLE = (
    "SKILL V3 HYBRID CHARACTER-HEAVY MULTI-SAMPLE PILOT — "
    "FINAL FRESH USER AUTHORIZATION"
)
CAMPAIGN_STATE_SCHEMA = "SkillV3HybridCampaignDurableStateV1"
CAMPAIGN_STATE_DOMAIN = "novel-flywheel-skill-v3-hybrid-campaign-state-v1"
CAMPAIGN_COMPLETION_DOMAIN = (
    "novel-flywheel-skill-v3-hybrid-campaign-completion-v1"
)
DRY_RUN_BLIND_DOMAIN = "novel-flywheel-skill-v3-hybrid-dry-run-blind-v1"
REAL_CAMPAIGN_ROOT_RELATIVE = Path(
    "canary-runs/skill-v3-hybrid-character-heavy-v1/real-campaign-v1"
)
CAMPAIGN_PERMISSION_STORE_RELATIVE = Path(
    "canary-approval-ledgers/skill-v3-hybrid-character-heavy-v1/"
    "campaign-permissions-v1"
)
CAMPAIGN_STATUS = {"ACTIVE", "STOPPED", "COMPLETED", "EXPIRED"}


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise HybridJitApprovalError("CAMPAIGN_PERMISSION_TIME_INVALID")
    return value.astimezone(timezone.utc)


def _utc_text(value: datetime) -> str:
    return _utc(value).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_utc(value: Any) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise HybridJitApprovalError("CAMPAIGN_PERMISSION_TIME_INVALID")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(timezone.utc)
    except ValueError as exc:
        raise HybridJitApprovalError("CAMPAIGN_PERMISSION_TIME_INVALID") from exc


def _sealed_values(repo_root: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    sealed = hybrid.load_sealed_pilot(repo_root)
    root = repo_root.resolve(strict=True) / hybrid.REPORT_ROOT
    route = json.loads(
        (root / "provider-model-route-binding-v1.json").read_text(encoding="utf-8")
    )
    destination = json.loads(
        (root / "destination-binding-v1.json").read_text(encoding="utf-8")
    )
    return sealed, route, destination


def render_final_authorization_text_v1(
    repo_root: Path, *, successor_head: str,
) -> bytes:
    """Render the only accepted final authorization bytes for this packet."""

    sealed, route, destination = _sealed_values(repo_root)
    samples = sealed["samples"]
    values = {
        "SUCCESSOR_HEAD": successor_head,
        "PILOT_ID": sealed["identity"]["PILOT_ID"],
        "EXPERIMENT_LOCK_SHA256": sealed["experiment"]["EXPERIMENT_LOCK_SHA256"],
        "EXECUTION_SEQUENCE": ",".join(hybrid.SEQUENCE),
        "SAMPLE_IDS": ",".join(str(row["SAMPLE_ID"]) for row in samples),
        "SAMPLE_LOCK_SHA256S": ",".join(
            str(row["SAMPLE_LOCK_SHA256"]) for row in samples
        ),
        "PROVIDER": route["PROVIDER"],
        "PROVIDER_DESCRIPTOR_SHA256": route["PROVIDER_DESCRIPTOR_SHA256"],
        "MODEL": route["MODEL"],
        "MODEL_BINDING_SHA256": route["MODEL_BINDING_SHA256"],
        "PROTOCOL": route["PROTOCOL"],
        "ROUTE_FINGERPRINT": route["ROUTE_FINGERPRINT"],
        "DESTINATION": (
            f"{destination['DESTINATION_ORIGIN']}:{destination['DESTINATION_PORT']}"
            f"{destination['DESTINATION_PATH']}"
        ),
        "OPERATOR_CLASSIFICATION": destination["OPERATOR_CLASSIFICATION"],
        "EGRESS_POLICY_SHA256S": ",".join(
            str(row["EGRESS_POLICY_SHA256"]) for row in samples
        ),
    }
    lines = [
        AUTHORIZATION_TITLE,
        "",
        "This text is an authorization template only. It is not authorization until the user sends it as a fresh explicit message.",
        "",
        *(f"{name}={value}" for name, value in values.items()),
        "PER_SAMPLE_OUTPUT_TOKEN_HARD_CAP=4624",
        "TOTAL_SIX_SAMPLE_OUTPUT_TOKEN_HARD_CAP=27744",
        "MAX_PROVIDER_REQUESTS_PER_SAMPLE=1",
        "TOTAL_PROVIDER_REQUESTS=6",
        "MAX_HTTP_POST_ATTEMPTS_PER_SAMPLE=1",
        "TOTAL_HTTP_POST_ATTEMPTS=6",
        "MAX_NETWORK_ATTEMPTS_PER_SAMPLE=1",
        "TOTAL_NETWORK_ATTEMPTS=6",
        "MAX_CAMPAIGN_ELAPSED_HOURS=10",
        "MONETARY_COST_CAP=UNKNOWN_NOT_SEALED",
        "I explicitly authorize the six sealed samples above, in the exact order above, with at most one paid request per sample and at most six paid requests total. I authorize only each sample's required system/context, task, authority, story slice, already model-visible reference-derived non-Skill guidance, its arm Skill context, output contract, and required Provider request metadata to be sent to the exact destination. I accept actual-fee risk because no trustworthy USD/CNY cap is sealed.",
        "Each next-eligible sample requires a separate JIT SkillV3HybridSampleJitSignedApprovalV1 followed by a separate fresh durable single-use nonce. Later approvals/nonces must not be precreated. No retry, transport retry, fallback, route switch, resume dispatch, second dispatch, alternate destination, cross-origin redirect, or replacement sample is authorized. Stop on the first blocked, invalid, drifted, failed, privacy-failed, or budget-exceeded state, or when the campaign expires. Blind mapping remains hidden until all required votes freeze. No Skill V3 cutover, Planning V2 cutover, or Full Short is authorized.",
        "",
    ]
    return "\n".join(lines).encode("utf-8")


def validate_final_authorization_text_v1(
    repo_root: Path,
    authorization_bytes: bytes,
    *,
    successor_head: str,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    expected = render_final_authorization_text_v1(
        repo_root, successor_head=successor_head,
    )
    if not isinstance(authorization_bytes, bytes) or authorization_bytes != expected:
        raise HybridJitApprovalError(
            "AUTHORIZATION_TEXT_EXACT_MISMATCH",
            operation="authorization_validator",
        )
    digest = _sha_bytes(authorization_bytes)
    if expected_sha256 is not None and digest != expected_sha256:
        raise HybridJitApprovalError(
            "AUTHORIZATION_TEXT_SHA256_MISMATCH",
            operation="authorization_validator",
        )
    return {
        "schema": "SkillV3HybridCanonicalAuthorizationValidationV1",
        "status": "EXACT",
        "authorization_text_sha256": digest,
        "successor_head": successor_head,
        "semantic_equivalence_relaxation": False,
        "external_action_count": 0,
    }


def campaign_permission_from_authorization_v1(
    *,
    repo_root: Path,
    permission_id: str,
    authorization_bytes: bytes,
    repository_head: str,
    issued_at: datetime,
    expires_at: datetime,
    offline_test_only: bool,
) -> dict[str, Any]:
    validation = validate_final_authorization_text_v1(
        repo_root, authorization_bytes, successor_head=repository_head,
    )
    body = campaign_permission_body_from_sealed(
        repo_root=repo_root,
        permission_id=permission_id,
        repository_head=repository_head,
        authorization_text_sha256=validation["authorization_text_sha256"],
        authorization_context_identity_sha256=domain_sha256(
            "novel-flywheel-skill-v3-hybrid-authorization-context-v1",
            {
                "authorization_text_sha256": validation["authorization_text_sha256"],
                "repository_head": repository_head,
                "exact_bytes": True,
            },
        ),
        issued_at=issued_at,
        expires_at=expires_at,
        offline_test_only=offline_test_only,
    )
    return seal_campaign_permission_v1(body)


def _state_body(
    *, permission: Mapping[str, Any], status: str,
    completed_sample_ids: Sequence[str], samples: Sequence[Mapping[str, Any]],
    provider_request_attempts: int, http_post_attempts: int,
    network_attempts: int, output_token_hard_cap_consumed: int,
    failure_reason: str | None, updated_at: datetime,
) -> dict[str, Any]:
    return {
        "schema": CAMPAIGN_STATE_SCHEMA,
        "version": 1,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "permission_id": permission["permission_id"],
        "campaign_permission_sha256": permission["campaign_permission_sha256"],
        "pilot_id": permission["pilot_id"],
        "experiment_lock_sha256": permission["experiment_lock_sha256"],
        "repository_head": permission["repository_head"],
        "status": status,
        "completed_sample_ids": list(completed_sample_ids),
        "sample_receipts": deepcopy(list(samples)),
        "provider_request_attempts": provider_request_attempts,
        "http_post_attempts": http_post_attempts,
        "network_attempts": network_attempts,
        "output_token_hard_cap_consumed": output_token_hard_cap_consumed,
        "failure_reason": failure_reason,
        "created_at": permission["issued_at"],
        "updated_at": _utc_text(updated_at),
        "expires_at": permission["expires_at"],
        "dry_run_only": bool(permission["offline_test_only"]),
    }


def _seal_state(body: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **deepcopy(dict(body)),
        "campaign_state_sha256": domain_sha256(CAMPAIGN_STATE_DOMAIN, body),
    }


def _validate_state(
    state: Mapping[str, Any], permission: Mapping[str, Any],
) -> dict[str, Any]:
    if state.get("schema") != CAMPAIGN_STATE_SCHEMA or state.get("version") != 1:
        raise HybridJitApprovalError("CAMPAIGN_STATE_INVALID")
    if state.get("status") not in CAMPAIGN_STATUS:
        raise HybridJitApprovalError("CAMPAIGN_STATE_INVALID")
    if (
        state.get("permission_id") != permission.get("permission_id")
        or state.get("campaign_permission_sha256")
        != permission.get("campaign_permission_sha256")
        or state.get("repository_head") != permission.get("repository_head")
    ):
        raise HybridJitApprovalError("CAMPAIGN_PERMISSION_SCOPE_DRIFT")
    body = dict(state)
    digest = body.pop("campaign_state_sha256", None)
    if digest != domain_sha256(CAMPAIGN_STATE_DOMAIN, body):
        raise HybridJitApprovalError("CAMPAIGN_STATE_SHA256_MISMATCH")
    completed = list(state.get("completed_sample_ids") or ())
    expected = list(permission["authorized_sample_ids"])
    if completed != expected[:len(completed)]:
        raise HybridJitApprovalError("CAMPAIGN_LEDGER_SEQUENCE_INVALID")
    for field, maximum in (
        ("provider_request_attempts", 6),
        ("http_post_attempts", 6),
        ("network_attempts", 6),
        ("output_token_hard_cap_consumed", 27744),
    ):
        value = state.get(field)
        if type(value) is not int or value < 0 or value > maximum:
            raise HybridJitApprovalError("CAMPAIGN_BUDGET_EXCEEDED")
    return deepcopy(dict(state))


class DurableHybridCampaignPermissionStoreV1:
    """Immutable exact permission plus atomic hash-only campaign progress."""

    def __init__(self, *, repo_root: Path, store_root: Path) -> None:
        self.repo_root = repo_root.resolve(strict=True)
        self.store_root = _outside_store(self.repo_root, store_root)
        self._lock_path = self.store_root / ".hybrid-campaign.lock"

    def _paths(self, permission_id: str) -> tuple[Path, Path]:
        key = domain_sha256(
            "novel-flywheel-skill-v3-hybrid-campaign-storage-key-v1",
            permission_id,
        )
        return (
            self.store_root / f"{key}.permission.json",
            self.store_root / f"{key}.campaign-state.json",
        )

    def create(
        self, permission: Mapping[str, Any], *, now: datetime,
        require_executable: bool,
    ) -> dict[str, Any]:
        value = validate_campaign_permission_v1(
            permission, repo_root=self.repo_root, now=now,
            require_executable=require_executable,
        )
        permission_path, state_path = self._paths(str(value["permission_id"]))
        state = _seal_state(_state_body(
            permission=value, status="ACTIVE", completed_sample_ids=[], samples=[],
            provider_request_attempts=0, http_post_attempts=0,
            network_attempts=0, output_token_hard_cap_consumed=0,
            failure_reason=None, updated_at=now,
        ))
        with _FileLock(self._lock_path):
            if permission_path.exists() or state_path.exists():
                raise HybridJitApprovalError("CAMPAIGN_PERMISSION_DOUBLE_CREATE")
            _write_exclusive(
                permission_path, value, "CAMPAIGN_PERMISSION_DOUBLE_CREATE",
            )
            try:
                _write_exclusive(
                    state_path, state, "CAMPAIGN_PERMISSION_DOUBLE_CREATE",
                )
            except BaseException:
                permission_path.unlink(missing_ok=True)
                raise
        return {"permission": value, "state": state}

    def _load_raw(self, permission_id: str) -> tuple[dict[str, Any], dict[str, Any], Path]:
        permission_path, state_path = self._paths(permission_id)
        permission = _read_json(
            permission_path, "CAMPAIGN_PERMISSION_NOT_FOUND",
        )
        state = _read_json(state_path, "CAMPAIGN_STATE_INVALID")
        return permission, state, state_path

    def load(
        self, permission_id: str, *, now: datetime, require_executable: bool,
        allow_completed: bool = False, allow_stopped: bool = False,
    ) -> dict[str, Any]:
        with _FileLock(self._lock_path):
            permission, state, state_path = self._load_raw(permission_id)
            validate_campaign_permission_v1(
                permission, repo_root=self.repo_root,
                now=_parse_utc(permission["issued_at"]),
                require_executable=require_executable,
            )
            exact_state = _validate_state(state, permission)
            if _utc(now) > _parse_utc(permission["expires_at"]):
                if exact_state["status"] == "ACTIVE":
                    body = dict(exact_state)
                    body.pop("campaign_state_sha256")
                    body["status"] = "EXPIRED"
                    body["failure_reason"] = "CAMPAIGN_PERMISSION_EXPIRED"
                    body["updated_at"] = _utc_text(now)
                    _atomic_replace(state_path, _seal_state(body))
                raise HybridJitApprovalError("CAMPAIGN_PERMISSION_EXPIRED")
            allowed = {"ACTIVE"}
            if allow_completed:
                allowed.add("COMPLETED")
            if allow_stopped:
                allowed.add("STOPPED")
            if exact_state["status"] not in allowed:
                raise HybridJitApprovalError("CAMPAIGN_PERMISSION_NOT_ACTIVE")
            return {"permission": permission, "state": exact_state}

    def _replace_state(
        self, permission_id: str, *, now: datetime,
        mutate: Callable[[dict[str, Any], dict[str, Any]], None],
    ) -> dict[str, Any]:
        with _FileLock(self._lock_path):
            permission, state, state_path = self._load_raw(permission_id)
            exact = _validate_state(state, permission)
            mutate(exact, permission)
            exact.pop("campaign_state_sha256", None)
            exact["updated_at"] = _utc_text(now)
            updated = _seal_state(exact)
            _atomic_replace(state_path, updated)
            return updated

    def record_success(
        self, permission_id: str, *, sample_id: str,
        sample_receipt: Mapping[str, Any], now: datetime,
    ) -> dict[str, Any]:
        def mutate(state: dict[str, Any], permission: dict[str, Any]) -> None:
            if state["status"] != "ACTIVE":
                raise HybridJitApprovalError("CAMPAIGN_PERMISSION_NOT_ACTIVE")
            completed = list(state["completed_sample_ids"])
            expected = list(permission["authorized_sample_ids"])
            if len(completed) >= len(expected) or expected[len(completed)] != sample_id:
                raise HybridJitApprovalError("LATER_SAMPLE_BEFORE_TURN")
            attempts = dict(sample_receipt.get("attempts") or {})
            for field in (
                "provider_dispatch_attempt_count", "http_post_attempt_count",
                "network_request_attempt_count",
            ):
                if attempts.get(field) != 1:
                    raise HybridJitApprovalError("CAMPAIGN_BUDGET_EXCEEDED")
            completed.append(sample_id)
            state["completed_sample_ids"] = completed
            state["provider_request_attempts"] += 1
            state["http_post_attempts"] += 1
            state["network_attempts"] += 1
            state["output_token_hard_cap_consumed"] += int(
                sample_receipt["output_token_hard_cap"],
            )
            state["sample_receipts"].append({
                "sample_id": sample_id,
                "sample_slot": sample_receipt["sample_slot"],
                "approval_id": sample_receipt["approval_id"],
                "signed_approval_sha256": sample_receipt["signed_approval_sha256"],
                "nonce_id": sample_receipt["nonce_id"],
                "artifact_file_sha256": sample_receipt["artifact_file_sha256"],
                "status": "SEALED_VALID",
                "dry_run_only": bool(permission["offline_test_only"]),
            })
            if len(completed) == len(expected):
                state["status"] = "COMPLETED"

        return self._replace_state(permission_id, now=now, mutate=mutate)

    def stop(
        self, permission_id: str, *, reason: str, now: datetime,
    ) -> dict[str, Any]:
        def mutate(state: dict[str, Any], _permission: dict[str, Any]) -> None:
            if state["status"] != "ACTIVE":
                raise HybridJitApprovalError("CAMPAIGN_PERMISSION_NOT_ACTIVE")
            state["status"] = "STOPPED"
            state["failure_reason"] = reason

        return self._replace_state(permission_id, now=now, mutate=mutate)

    def assert_next_eligible(
        self, permission_id: str, *, sample_id: str, now: datetime,
        require_executable: bool,
    ) -> dict[str, Any]:
        loaded = self.load(
            permission_id, now=now, require_executable=require_executable,
        )
        state = loaded["state"]
        permission = loaded["permission"]
        completed = list(state["completed_sample_ids"])
        expected = list(permission["authorized_sample_ids"])
        if len(completed) >= len(expected):
            raise HybridJitApprovalError("CAMPAIGN_ALREADY_COMPLETE")
        if expected[len(completed)] != sample_id:
            raise HybridJitApprovalError("LATER_SAMPLE_BEFORE_TURN")
        return loaded


DispatcherFactory = Callable[[dict[str, object], str], Any]


@dataclass(frozen=True)
class HybridCampaignExecutionEnvironmentV1:
    repo_root: Path
    campaign_store: DurableHybridCampaignPermissionStoreV1
    approval_store: DurableHybridApprovalStoreV1
    nonce_store: DurablePilotNonceStoreV1
    output_root: Path
    dispatcher_factory: DispatcherFactory
    dry_run_only: bool

    @classmethod
    def offline(
        cls, *, repo_root: Path, store_parent: Path, output_root: Path,
        dispatcher_factory: DispatcherFactory,
    ) -> "HybridCampaignExecutionEnvironmentV1":
        repo = repo_root.resolve(strict=True)
        parent = store_parent.resolve(strict=False)
        return cls(
            repo_root=repo,
            campaign_store=DurableHybridCampaignPermissionStoreV1(
                repo_root=repo, store_root=parent / "campaign",
            ),
            approval_store=DurableHybridApprovalStoreV1(
                repo_root=repo, store_root=parent / "approvals",
            ),
            nonce_store=DurablePilotNonceStoreV1(
                repo_root=repo, store_root=parent / "nonces",
            ),
            output_root=output_root,
            dispatcher_factory=dispatcher_factory,
            dry_run_only=True,
        )

    @classmethod
    def canonical(
        cls, *, repo_root: Path, permission_id: str,
    ) -> "HybridCampaignExecutionEnvironmentV1":
        """Build production wiring without credentials, approvals, or nonces."""

        repo = repo_root.resolve(strict=True)
        settings = default_settings()
        destination = resolve_a1_destination_binding_v1(
            repo_root=repo, route_database=repo / "data" / "app.db",
        )
        execution_parent = (
            settings.data_dir / REAL_CAMPAIGN_ROOT_RELATIVE
            / domain_sha256(
                "novel-flywheel-skill-v3-hybrid-real-campaign-key-v1",
                permission_id,
            )
        )

        def factory(lock: dict[str, object], approval_id: str) -> RealPilotDispatcherV1:
            return RealPilotDispatcherV1(
                repo_root=repo,
                route_database=repo / "data" / "app.db",
                execution_root=execution_parent / "dispatch" / domain_sha256(
                    "novel-flywheel-skill-v3-hybrid-real-dispatch-key-v1",
                    approval_id,
                ),
                approved_destination_authority={
                    "destination_origin": destination.origin,
                    "destination_origin_sha256": destination.destination_origin_sha256,
                    "destination_path_or_prefix": destination.api_path,
                    "destination_operator_class": destination.operator_class,
                    "egress_policy_sha256": str(lock["EGRESS_POLICY_SHA256"]),
                    "cross_origin_redirect_allowed": False,
                    "unbound_proxy_route_allowed": False,
                },
                expected_sampling_policy_sha256=str(lock["SAMPLING_FINGERPRINT"]),
                expected_output_cap=int(lock["OUTPUT_CAP"]),
            )

        return cls(
            repo_root=repo,
            campaign_store=DurableHybridCampaignPermissionStoreV1(
                repo_root=repo,
                store_root=(
                    settings.data_dir / CAMPAIGN_PERMISSION_STORE_RELATIVE
                ),
            ),
            approval_store=DurableHybridApprovalStoreV1(
                repo_root=repo, store_root=default_hybrid_approval_store_root(),
            ),
            nonce_store=DurablePilotNonceStoreV1(
                repo_root=repo, store_root=default_nonce_store_root(),
            ),
            output_root=execution_parent / "outputs",
            dispatcher_factory=factory,
            dry_run_only=False,
        )


def _project_permission(
    permission: Mapping[str, Any], sealed: Mapping[str, Any], sample_id: str,
    offline_test: bool,
) -> dict[str, Any]:
    return {
        "schema": "HybridVerifiedCampaignPermissionProjectionV1",
        "non_executable": offline_test,
        "active_campaign_permission": True,
        "pilot_id": permission["pilot_id"],
        "sample_id": sample_id,
        "experiment_lock_sha256": permission["experiment_lock_sha256"],
        "successor_head": sealed["approval"]["CURRENT_SUCCESSOR_HEAD"],
        "scopes": list(hybrid.PERMISSION_SCOPES),
    }


def _project_approval(
    approval: Mapping[str, Any], *, offline_test: bool,
) -> dict[str, Any]:
    """Project an approval already validated at the campaign's frozen clock."""

    return {
        "schema": "HybridVerifiedExecutableApprovalProjectionV1",
        "non_executable": offline_test,
        "approval_id": approval["approval_id"],
        "pilot_id": approval["pilot_id"],
        "sample_id": approval["sample_id"],
        "sample_lock_sha256": approval["sample_lock_sha256"],
        "experiment_lock_sha256": approval["experiment_lock_sha256"],
        "model_input_component_binding_sha256": approval[
            "model_input_component_sha256"
        ],
        "route_fingerprint": approval["route_fingerprint"],
        "destination_origin": approval["destination_origin"],
        "egress_policy_sha256": approval["egress_policy_sha256"],
        "wire_input_sha256": approval["wire_input_sha256"],
        "nonce_policy_version": hybrid.NONCE_POLICY_VERSION,
        "real_dispatcher_version": hybrid.REAL_DISPATCHER_VERSION,
        "nonce_state": "NOT_CREATED",
        "signed_approval_sha256": approval["signed_approval_sha256"],
        "repository_head": approval["current_execution_head"],
        "usage_status": "unused",
        "expired": False,
    }


async def run_hybrid_campaign_v1(
    *, environment: HybridCampaignExecutionEnvironmentV1,
    permission_id: str, now: datetime, offline_test: bool,
) -> dict[str, Any]:
    """Run the exact next-eligible sequence; stop and persist on first failure."""

    if offline_test is not environment.dry_run_only:
        raise HybridJitApprovalError("CAMPAIGN_EXECUTION_MODE_MISMATCH")
    loaded = environment.campaign_store.load(
        permission_id, now=now, require_executable=not offline_test,
    )
    permission = loaded["permission"]
    state = loaded["state"]
    sealed = hybrid.load_sealed_pilot(environment.repo_root)
    while state["status"] == "ACTIVE":
        step_now = now if offline_test else datetime.now(timezone.utc)
        loaded = environment.campaign_store.load(
            permission_id, now=step_now,
            require_executable=not offline_test,
        )
        permission = loaded["permission"]
        state = loaded["state"]
        completed = list(state["completed_sample_ids"])
        lock = sealed["samples"][len(completed)]
        sample_id = str(lock["SAMPLE_ID"])
        environment.campaign_store.assert_next_eligible(
            permission_id, sample_id=sample_id, now=step_now,
            require_executable=not offline_test,
        )
        approval_id = (
            (
                f"offline-hybrid-jit-{int(lock['SEQUENCE_POSITION'])}-"
                + domain_sha256(
                    "novel-flywheel-skill-v3-hybrid-offline-approval-id-v1",
                    {
                        "permission": permission["campaign_permission_sha256"],
                        "sample": sample_id,
                    },
                )[:16]
            )
            if offline_test else f"sv3h-jit-{secrets.token_hex(16)}"
        )
        approval: dict[str, Any] | None = None
        try:
            approval = create_one_hybrid_sample_jit_approval(
                repo_root=environment.repo_root,
                store=environment.approval_store,
                permission=permission,
                sample_id=sample_id,
                completed_sample_ids=completed,
                approval_id=approval_id,
                attempt_counters=ZERO_ATTEMPT_COUNTERS,
                nonce_preexists=not environment.nonce_store.is_reusable(
                    pilot_id=str(permission["pilot_id"]),
                    sample_id=sample_id,
                    approval_id=approval_id,
                ),
                now=step_now,
                expires_at=min(
                    step_now + timedelta(minutes=30),
                    _parse_utc(permission["expires_at"]),
                ),
                offline_test=offline_test,
            )
            approval = environment.approval_store.load(
                approval_id, now=step_now,
            )["approval"]
            validate_approval_domain_v1(
                approval,
                repo_root=environment.repo_root,
                permission=permission,
                completed_sample_ids=completed,
                attempt_counters=ZERO_ATTEMPT_COUNTERS,
                nonce_preexists=False,
                now=step_now,
                require_executable=not offline_test,
            )
            nonce_store = HybridApprovalBoundNonceAdapter(
                delegate=environment.nonce_store, approval=approval,
            )
            dispatcher = environment.dispatcher_factory(lock, approval_id)
            ledger = hybrid.HybridPilotLedger(sample_states={
                row["SAMPLE_ID"]: f"{row['SAMPLE_SLOT']}:SEALED_VALID"
                for row in sealed["samples"][:len(completed)]
            })
            result = await hybrid.launch_one_sealed_hybrid_sample(
                repo_root=environment.repo_root,
                pilot_id=str(permission["pilot_id"]),
                sample_id=sample_id,
                expected_sample_lock_sha256=str(lock["SAMPLE_LOCK_SHA256"]),
                expected_experiment_lock_sha256=str(lock["EXPERIMENT_LOCK_SHA256"]),
                permission=_project_permission(
                    permission, sealed, sample_id, offline_test,
                ),
                signed_approval=_project_approval(
                    approval, offline_test=offline_test,
                ),
                nonce_store=nonce_store,
                ledger=ledger,
                dispatcher=dispatcher,
                output_root=environment.output_root / str(lock["SAMPLE_SLOT"]),
                offline_fake=offline_test,
            )
            nonce = environment.nonce_store.load(
                pilot_id=str(permission["pilot_id"]),
                sample_id=sample_id,
                approval_id=approval_id,
            )
            receipt_sha = domain_sha256(
                "novel-flywheel-skill-v3-hybrid-campaign-sample-receipt-v1",
                {
                    "sample_id": sample_id,
                    "artifact_file_sha256": result["artifact_file_sha256"],
                    "nonce_receipt_sha256": nonce["nonce_receipt_sha256"],
                },
            )
            approval_state = environment.approval_store.consume(
                approval_id, execution_receipt_sha256=receipt_sha,
            )
            sample_receipt = {
                **result,
                "approval_id": approval_id,
                "signed_approval_sha256": approval["signed_approval_sha256"],
                "approval_state": approval_state["usage_state"],
                "nonce_id": nonce["nonce_id"],
                "nonce_state": nonce["state"],
                "output_token_hard_cap": int(lock["OUTPUT_CAP"]),
            }
            state = environment.campaign_store.record_success(
                permission_id, sample_id=sample_id,
                sample_receipt=sample_receipt,
                now=(step_now if offline_test else datetime.now(timezone.utc)),
            )
        except BaseException as exc:
            reason = str(getattr(exc, "reason_code", "CAMPAIGN_SAMPLE_FAILED"))
            if approval is not None:
                try:
                    environment.approval_store.invalidate(
                        approval_id, reason_code=reason,
                    )
                except HybridJitApprovalError:
                    pass
            try:
                environment.campaign_store.stop(
                    permission_id, reason=reason,
                    now=(step_now if offline_test else datetime.now(timezone.utc)),
                )
            except HybridJitApprovalError:
                pass
            raise
    exact = environment.campaign_store.load(
        permission_id,
        now=(now if offline_test else datetime.now(timezone.utc)),
        require_executable=not offline_test,
        allow_completed=True,
    )["state"]
    if exact["status"] != "COMPLETED":
        raise HybridJitApprovalError("CAMPAIGN_PERMISSION_NOT_ACTIVE")
    completion_body = {
        "schema": "SkillV3HybridCampaignCompletionReceiptV1",
        "permission_id": permission_id,
        "campaign_state_sha256": exact["campaign_state_sha256"],
        "sample_count": len(exact["sample_receipts"]),
        "valid_sample_count": sum(
            row["status"] == "SEALED_VALID" for row in exact["sample_receipts"]
        ),
        "approval_states": ["CONSUMED"] * len(exact["sample_receipts"]),
        "nonce_states": ["CONSUMED"] * len(exact["sample_receipts"]),
        "synthetic_http_attempt_count": exact["http_post_attempts"],
        "real_external_action_count": 0 if offline_test else exact["network_attempts"],
        "dry_run_only": offline_test,
        "status": "COMPLETED",
    }
    completion = {
        **completion_body,
        "completion_receipt_sha256": domain_sha256(
            CAMPAIGN_COMPLETION_DOMAIN, completion_body,
        ),
    }
    environment.output_root.mkdir(parents=True, exist_ok=True)
    (environment.output_root / "campaign-completion-v1.json").write_bytes(
        canonical_json_bytes(completion) + b"\n",
    )
    blind = materialize_dry_run_blind_bundle_v1(
        output_root=environment.output_root / "dry-run-blind-bundle-v1",
        artifacts=exact["sample_receipts"],
    ) if offline_test else None
    return {
        **completion,
        "dry_run_blind_bundle_sha256": (
            blind["dry_run_blind_bundle_sha256"] if blind else None
        ),
    }


async def execute_authorized_hybrid_campaign_once_v1(
    *, repo_root: Path, authorization_bytes: bytes, permission_id: str,
    issued_at: datetime, expires_at: datetime,
) -> dict[str, Any]:
    """Future real entry: exact fresh bytes -> permission -> one campaign.

    Merely importing or constructing this function performs no credential,
    approval, nonce, provider-client, or network action.
    """

    head, _branch = current_git_identity(repo_root, require_clean=True)
    permission = campaign_permission_from_authorization_v1(
        repo_root=repo_root,
        permission_id=permission_id,
        authorization_bytes=authorization_bytes,
        repository_head=head,
        issued_at=issued_at,
        expires_at=expires_at,
        offline_test_only=False,
    )
    environment = HybridCampaignExecutionEnvironmentV1.canonical(
        repo_root=repo_root, permission_id=permission_id,
    )
    environment.campaign_store.create(
        permission, now=issued_at, require_executable=True,
    )
    return await run_hybrid_campaign_v1(
        environment=environment,
        permission_id=permission_id,
        now=issued_at,
        offline_test=False,
    )


def campaign_transport_preflight_v1(repo_root: Path) -> dict[str, Any]:
    """Resolve the exact real adapter metadata without credentials or network."""

    sealed, route, destination = _sealed_values(repo_root)
    resolved = resolve_a1_destination_binding_v1(
        repo_root=repo_root.resolve(strict=True),
        route_database=repo_root.resolve(strict=True) / "data" / "app.db",
    )
    expected_destination = (
        f"{destination['DESTINATION_ORIGIN']}:{destination['DESTINATION_PORT']}"
        f"{destination['DESTINATION_PATH']}"
    )
    if (
        resolved.origin != destination["DESTINATION_ORIGIN"]
        or resolved.hostname != destination["DESTINATION_HOSTNAME"]
        or resolved.port != destination["DESTINATION_PORT"]
        or resolved.api_path != destination["DESTINATION_PATH"]
        or resolved.route_fingerprint != route["ROUTE_FINGERPRINT"]
    ):
        raise HybridJitApprovalError("REAL_TRANSPORT_CONFIGURATION_UNRESOLVED")
    return {
        "schema": "SkillV3HybridRealTransportPreflightV1",
        "status": "EXACT",
        "provider": route["PROVIDER"],
        "model": route["MODEL"],
        "protocol": route["PROTOCOL"],
        "route_fingerprint": route["ROUTE_FINGERPRINT"],
        "destination": expected_destination,
        "hostname": resolved.hostname,
        "port": resolved.port,
        "path": resolved.api_path,
        "operator_classification": destination["OPERATOR_CLASSIFICATION"],
        "redirect_policy": "CROSS_ORIGIN_REDIRECT_FORBIDDEN",
        "proxy_policy": "UNBOUND_PROXY_FORBIDDEN",
        "base_url_override_policy": "UNBOUND_OVERRIDE_FORBIDDEN",
        "fallback_policy": "NO_FALLBACK_DESTINATION",
        "alternate_destination_count": 0,
        "sample_count": len(sealed["samples"]),
        "credential_lookup_count": 0,
        "network_call_count": 0,
    }


def materialize_dry_run_blind_bundle_v1(
    *, output_root: Path, artifacts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Exercise blind staging without retaining real sample identities or prose."""

    output_root.mkdir(parents=True, exist_ok=False)
    rows = []
    for index, artifact in enumerate(artifacts, start=1):
        digest = str(artifact.get("artifact_file_sha256") or "")
        if len(digest) != 64:
            raise HybridJitApprovalError("DRY_RUN_BLIND_ARTIFACT_INVALID")
        rows.append({
            "anonymous_id": domain_sha256(
                "novel-flywheel-skill-v3-hybrid-dry-run-anonymous-id-v1",
                {"ordinal": index, "artifact_file_sha256": digest},
            )[:24],
            "artifact_file_sha256": digest,
        })
    body = {
        "schema": "SkillV3HybridDryRunBlindBundleV1",
        "dry_run_only": True,
        "production_sample_eligible": False,
        "mapping_hidden": True,
        "raw_prose_included": False,
        "artifacts": rows,
    }
    value = {
        **body,
        "dry_run_blind_bundle_sha256": domain_sha256(DRY_RUN_BLIND_DOMAIN, body),
    }
    (output_root / "dry-run-blind-bundle-v1.json").write_bytes(
        canonical_json_bytes(value) + b"\n",
    )
    return value


__all__ = [
    "DurableHybridCampaignPermissionStoreV1",
    "HybridCampaignExecutionEnvironmentV1",
    "campaign_permission_from_authorization_v1",
    "campaign_transport_preflight_v1",
    "execute_authorized_hybrid_campaign_once_v1",
    "materialize_dry_run_blind_bundle_v1",
    "render_final_authorization_text_v1",
    "run_hybrid_campaign_v1",
    "validate_final_authorization_text_v1",
]
