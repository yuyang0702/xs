"""Pilot-only real execution boundary for the sealed Skill V3 experiment.

Nothing in the normal application imports this module.  The canonical entry
accepts only a current-chat permission receipt and an external approval ID;
all request, route, model, contract, output-cap, nonce-store, and dispatcher
choices are reconstructed from sealed repository and local runtime authority.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any, Callable, Mapping

from novel_flywheel.config import default_settings
from novel_flywheel.db import Database
from novel_flywheel.providers.registry import ProviderRegistry
from novel_flywheel.providers.http import SingleDispatchTransportPolicyV1
from novel_flywheel.secrets import KeyringSecretStore, SecretStore
from novel_flywheel.structured_artifacts import (
    StructuredArtifactContract,
    StructuredOutputRequirement,
)
from tools.canary import skill_v3_character_heavy_pilot as pilot
from tools.canary import skill_v3_pilot_approval_store as approvals
from tools.canary import slice1_phase_b_current_skill as current_arm
from tools.canary.skill_v3_a1_destination_binding import (
    DestinationBindingV1,
    a1_egress_policy_v1,
    request_target_is_exact_v1,
    resolve_a1_destination_binding_v1,
    validate_destination_authority_v1,
)
from tools.canary.skill_v3_pilot_nonce_store import (
    DurablePilotNonceStoreV1,
    NONCE_POLICY_VERSION,
    default_nonce_store_root,
)


REAL_DISPATCHER_VERSION = pilot.REAL_DISPATCHER_VERSION
REAL_EXECUTION_ROOT_RELATIVE = Path(
    "canary-runs/skill-v3-character-heavy-multi-sample-v1/real-boundary-v1"
)


class _CountingSecretStore:
    def __init__(self, delegate: SecretStore) -> None:
        self.delegate = delegate
        self.lookup_count = 0

    def get(self, provider_id: str) -> str | None:
        self.lookup_count += 1
        return self.delegate.get(provider_id)

    def set(self, provider_id: str, value: str) -> None:
        self.delegate.set(provider_id, value)

    def delete(self, provider_id: str) -> None:
        self.delegate.delete(provider_id)


@dataclass(frozen=True)
class OfflineDispatchDependenciesV1:
    """Explicit test-only seam below the real dispatcher and request builder."""

    secret_store: SecretStore
    client_factory: Callable[[], Any]


class _NonceAwareAttemptObserver:
    def __init__(
        self,
        attempts: pilot.AttemptGuard,
        nonce_store: Any | None,
        nonce_binding: Mapping[str, str] | None,
    ) -> None:
        self.attempts = attempts
        self.nonce_store = nonce_store
        self.nonce_binding = dict(nonce_binding or {})

    def before_http_post(self) -> None:
        self.attempts.before_http_post()

    def before_network_request(self) -> None:
        self.attempts.before_network_request()
        if self.nonce_store is not None:
            self.nonce_store.note_network_attempt(**self.nonce_binding)


class RealPilotDispatcherV1:
    """Exact-route, one-shot dispatcher using production Runtime components."""

    retry_disabled = True
    fallback_disabled = True
    route_switch_disabled = True
    resume_disabled = True
    version = REAL_DISPATCHER_VERSION

    def __init__(
        self,
        *,
        repo_root: Path,
        route_database: Path,
        execution_root: Path,
        offline_dependencies: OfflineDispatchDependenciesV1 | None = None,
        approved_destination_authority: Mapping[str, Any] | None = None,
        expected_sampling_policy_sha256: str | None = None,
        expected_output_cap: int | None = None,
    ) -> None:
        self.repo_root = repo_root.resolve(strict=True)
        self.route_database = route_database.resolve(strict=True)
        self.execution_root = execution_root.resolve(strict=False)
        self.offline_dependencies = offline_dependencies
        self.offline_fake = offline_dependencies is not None
        self.transport_policy = SingleDispatchTransportPolicyV1.phase_b().definition()
        self.credential_lookup_count = 0
        self.provider_client_creation_count = 0
        self._last_transport_attempts: dict[str, Any] = {
            "model_logical_calls": 0,
            "http_post_attempts": 0,
            "real_provider_request_attempts": 0,
            "network_request_attempts": 0,
        }
        self._nonce_store: Any | None = None
        self._nonce_binding: dict[str, str] | None = None
        self._preflight = self._preflight_route()
        self.destination_binding = resolve_a1_destination_binding_v1(
            repo_root=self.repo_root,
            route_database=self.route_database,
        )
        self.destination_check_count = 1
        self._approved_destination_authority = dict(
            approved_destination_authority or {},
        )
        if self._approved_destination_authority:
            validate_destination_authority_v1(
                self._approved_destination_authority,
                destination=self.destination_binding,
                egress_policy_sha256=str(
                    self._approved_destination_authority.get("egress_policy_sha256") or "",
                ),
            )
        selected = self._preflight["routes"][0]
        self.route_fingerprint = str(selected["route_fingerprint"])
        self.provider_descriptor_sha256 = str(selected["provider_descriptor_sha256"])
        self.model_binding_sha256 = str(selected["model_binding_sha256"])
        if expected_sampling_policy_sha256 is None or expected_output_cap is None:
            sealed = pilot.load_sealed_pilot(self.repo_root)
            route_lock = sealed["state"]["lock"]["route_model_provider_client"]
            expected_sampling_policy_sha256 = str(
                route_lock["sampling_policy_sha256"]
            )
            expected_output_cap = int(sealed["locks"][0]["output_cap"])
        if len(str(expected_sampling_policy_sha256)) != 64:
            raise pilot.PilotBoundaryError("WRONG_SAMPLING_POLICY")
        if int(expected_output_cap) <= 0:
            raise pilot.PilotBoundaryError("WRONG_OUTPUT_CAP")
        self.sampling_policy_sha256 = str(expected_sampling_policy_sha256)
        self.output_cap = int(expected_output_cap)

    def _preflight_route(self) -> dict[str, Any]:
        try:
            binding = current_arm.resolve_route_binding(self.route_database)
        except Exception as exc:
            raise pilot.PilotBoundaryError("WRONG_ROUTE") from exc
        selected = binding["routes"][0]
        if (
            binding.get("selected_route") != "primary"
            or selected.get("adapter_family") != "AnthropicAdapter"
            or selected.get("provider_family") != "anthropic"
            or selected.get("route_fingerprint")
            != current_arm.EXPECTED_PRIMARY_ROUTE_FINGERPRINT
            or selected.get("provider_descriptor_sha256")
            != current_arm.EXPECTED_PRIMARY_DESCRIPTOR
            or selected.get("model_binding_sha256")
            != current_arm.EXPECTED_PRIMARY_MODEL
        ):
            raise pilot.PilotBoundaryError("WRONG_ROUTE")
        return binding

    def bind_nonce_reservation(
        self, *, nonce_store: Any, nonce_binding: Mapping[str, str],
    ) -> None:
        if self._nonce_binding is not None:
            raise pilot.PilotBoundaryError("NONCE_REUSE")
        self._nonce_store = nonce_store
        self._nonce_binding = dict(nonce_binding)

    def transport_attempt_snapshot(self) -> dict[str, Any]:
        return dict(self._last_transport_attempts)

    async def dispatch(
        self, model_input: pilot.ReconstructedInput, attempts: pilot.AttemptGuard,
    ) -> str:
        if self._nonce_binding is None:
            raise pilot.PilotBoundaryError("MISSING_DURABLE_NONCE_BINDING")
        current_destination = resolve_a1_destination_binding_v1(
            repo_root=self.repo_root,
            route_database=self.route_database,
        )
        self.destination_check_count += 1
        if current_destination != self.destination_binding:
            raise pilot.PilotBoundaryError(
                "SKILL_V3_A1_REAL_DISPATCH_NO_GO_DESTINATION_DRIFT",
            )
        if self._approved_destination_authority:
            try:
                validate_destination_authority_v1(
                    self._approved_destination_authority,
                    destination=current_destination,
                    egress_policy_sha256=str(
                        self._approved_destination_authority.get("egress_policy_sha256") or "",
                    ),
                )
            except Exception as exc:
                raise pilot.PilotBoundaryError(
                    "SKILL_V3_A1_REAL_DISPATCH_NO_GO_DESTINATION_DRIFT",
                ) from exc
        if (
            model_input.route_fingerprint != self.route_fingerprint
            or model_input.provider_descriptor_sha256 != self.provider_descriptor_sha256
            or model_input.model_binding_sha256 != self.model_binding_sha256
            or model_input.sampling_policy_sha256 != self.sampling_policy_sha256
            or model_input.output_cap != self.output_cap
        ):
            raise pilot.PilotBoundaryError("WRONG_ROUTE")
        # The exact metadata-only route check above happened before this point.
        attempts.before_provider_dispatch()
        self.execution_root.mkdir(parents=True, exist_ok=False)
        runtime_root = self.execution_root / "runtime"
        runtime_root.mkdir()
        isolated_database = runtime_root / "app.db"
        shutil.copy2(self.route_database, isolated_database)

        dependencies = self.offline_dependencies
        secrets = _CountingSecretStore(
            dependencies.secret_store if dependencies is not None else KeyringSecretStore(),
        )
        observer = _NonceAwareAttemptObserver(
            attempts, self._nonce_store, self._nonce_binding,
        )

        outer = self

        class PilotRegistry(ProviderRegistry):
            last_adapter = None
            replaced_client = None

            def resolve(self, provider_id: str, model_id: str):
                resolved = super().resolve(provider_id, model_id)
                outer.provider_client_creation_count += 1
                if resolved.route_fingerprint != outer.route_fingerprint:
                    raise pilot.PilotBoundaryError("WRONG_ROUTE")
                self.last_adapter = resolved.adapter
                target_path = (
                    "messages"
                    if resolved.adapter.base_url.endswith("/v1")
                    else "v1/messages"
                )
                target_url = f"{resolved.adapter.base_url}/{target_path}"
                if not request_target_is_exact_v1(
                    target_url, outer.destination_binding,
                ):
                    raise pilot.PilotBoundaryError(
                        "SKILL_V3_A1_REAL_DISPATCH_NO_GO_DESTINATION_DRIFT",
                    )
                outer.destination_check_count += 1
                if getattr(resolved.adapter.client, "follow_redirects", True):
                    raise pilot.PilotBoundaryError("CROSS_ORIGIN_REDIRECT")
                if getattr(resolved.adapter.client, "_mounts", None):
                    raise pilot.PilotBoundaryError("UNBOUND_PROXY_ROUTE")
                if dependencies is not None:
                    self.replaced_client = getattr(resolved.adapter, "client", None)
                    resolved.adapter.client = dependencies.client_factory()
                return resolved

        registry = PilotRegistry(
            Database(isolated_database),
            secrets,
            transport_policy=SingleDispatchTransportPolicyV1.phase_b(),
            attempt_observer=observer,
        )
        from novel_flywheel.models import ModelGateway

        gateway = ModelGateway(registry.db, registry)
        contract = StructuredArtifactContract(
            name="planning_event_realization_shadow_v1",
            version=1,
            schema=pilot.EventRealizationCandidateV1.model_json_schema(),
            runtime_authority={
                "model_input_component_binding_sha256": (
                    model_input.model_input_component_binding_sha256
                ),
            },
        )
        try:
            result = await gateway.complete_route(
                "primary",
                "planning",
                model_input.system,
                model_input.user,
                max_output_tokens=model_input.output_cap,
                contract=contract,
                structured_requirement=StructuredOutputRequirement.PLAIN_TEXT,
            )
            return result.text
        except asyncio.CancelledError:
            raise
        except pilot.PilotBoundaryError:
            raise
        except Exception as exc:
            raise pilot.PilotBoundaryError("PROVIDER_BOUNDARY_FAILED") from exc
        finally:
            self.credential_lookup_count = secrets.lookup_count
            adapter = registry.last_adapter
            if adapter is not None:
                self._last_transport_attempts = adapter.transport_attempt_snapshot()
                await adapter.client.aclose()
            if registry.replaced_client is not None:
                await registry.replaced_client.aclose()


@dataclass(frozen=True)
class RealPilotExecutionEnvironmentV1:
    repo_root: Path
    route_database: Path
    approval_store_root: Path
    nonce_store_root: Path
    execution_parent_root: Path

    @classmethod
    def canonical(cls, repo_root: Path) -> "RealPilotExecutionEnvironmentV1":
        repo = repo_root.resolve(strict=True)
        settings = default_settings()
        return cls(
            repo_root=repo,
            route_database=(repo / "data" / "app.db"),
            approval_store_root=approvals.default_successor_approval_store_root(),
            nonce_store_root=default_nonce_store_root(),
            execution_parent_root=settings.data_dir / REAL_EXECUTION_ROOT_RELATIVE,
        )

    def dispatcher_for(
        self, approval_id: str,
        *, approved_destination_authority: Mapping[str, Any] | None = None,
        expected_sampling_policy_sha256: str | None = None,
        expected_output_cap: int | None = None,
    ) -> RealPilotDispatcherV1:
        execution_key = hashlib.sha256(approval_id.encode("utf-8")).hexdigest()
        return RealPilotDispatcherV1(
            repo_root=self.repo_root,
            route_database=self.route_database,
            execution_root=self.execution_parent_root / execution_key,
            approved_destination_authority=approved_destination_authority,
            expected_sampling_policy_sha256=expected_sampling_policy_sha256,
            expected_output_cap=expected_output_cap,
        )

    def nonce_store(self) -> DurablePilotNonceStoreV1:
        return DurablePilotNonceStoreV1(
            repo_root=self.repo_root,
            store_root=self.nonce_store_root,
        )


def canonical_real_execution_environment_v1(
    repo_root: Path,
) -> RealPilotExecutionEnvironmentV1:
    """Build metadata-only canonical wiring; do not reserve or dispatch."""

    return RealPilotExecutionEnvironmentV1.canonical(repo_root)


class DestinationBoundNonceStoreV2Adapter:
    """Bind the V3 approval destination into the atomic durable nonce receipt."""

    def __init__(
        self,
        *,
        delegate: DurablePilotNonceStoreV1,
        destination: DestinationBindingV1,
        approval: Mapping[str, Any],
    ) -> None:
        self.delegate = delegate
        self.destination = destination
        self.approval = dict(approval)
        validate_destination_authority_v1(
            self.approval,
            destination=self.destination,
            egress_policy_sha256=str(
                a1_egress_policy_v1(self.delegate.repo_root)["egress_policy_sha256"],
            ),
        )

    def reserve(self, **bindings: Any) -> Mapping[str, Any]:
        if (
            bindings.get("signed_approval_sha256")
            != self.approval.get("signed_approval_sha256")
            or bindings.get("route_fingerprint")
            != self.destination.route_fingerprint
        ):
            raise pilot.PilotBoundaryError("NONCE_DESTINATION_SHA_MISMATCH")
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


async def launch_real_a1_once_v1(
    *,
    repo_root: Path,
    permission: Mapping[str, Any],
    approval_id: str,
) -> dict[str, Any]:
    """Legacy V2 approval entry; destination-unbound execution is disabled."""

    raise pilot.PilotBoundaryError("DESTINATION_BOUND_APPROVAL_V3_REQUIRED")


async def launch_real_a1_once_v3(
    *,
    repo_root: Path,
    permission: Mapping[str, Any],
    approval_id: str,
) -> dict[str, Any]:
    """Destination-bound A1 launcher for a separately authorized future task."""

    environment = canonical_real_execution_environment_v1(repo_root)
    sealed = pilot.load_sealed_pilot(environment.repo_root)
    lock = next(row for row in sealed["locks"] if row["sample_slot"] == "A1")
    model_input = pilot.reconstruct_sample_input(
        environment.repo_root, str(lock["sample_id"]),
    )
    destination = resolve_a1_destination_binding_v1(
        repo_root=environment.repo_root,
        route_database=environment.route_database,
    )
    egress = a1_egress_policy_v1(environment.repo_root)
    approval = approvals.load_successor_signed_approval_v3(
        repo_root=environment.repo_root,
        store_root=environment.approval_store_root,
        approval_id=approval_id,
        expected_sample_id=str(lock["sample_id"]),
        expected_sample_lock_sha256=str(lock["sample_lock_sha256"]),
        expected_parent_experiment_lock_sha256=pilot.PARENT_EXPERIMENT_LOCK_SHA256,
        expected_wire_input_sha256=model_input.wire_input_sha256,
        expected_model_input_component_binding_sha256=model_input.model_input_component_binding_sha256,
        expected_provider_descriptor_sha256=model_input.provider_descriptor_sha256,
        expected_model_binding_sha256=model_input.model_binding_sha256,
        expected_route_fingerprint=model_input.route_fingerprint,
        expected_sampling_policy_sha256=model_input.sampling_policy_sha256,
        expected_validator_sha256=model_input.validator_sha256,
        expected_max_output_tokens=model_input.output_cap,
        expected_nonce_policy_version=NONCE_POLICY_VERSION,
        expected_real_dispatcher_version=REAL_DISPATCHER_VERSION,
        expected_destination_origin=destination.origin,
        expected_destination_origin_sha256=destination.destination_origin_sha256,
        expected_destination_path_or_prefix=destination.api_path,
        expected_destination_operator_class=destination.operator_class,
        expected_egress_policy_sha256=str(egress["egress_policy_sha256"]),
    )
    destination_authority = {
        field: approval[field]
        for field in (
            "destination_origin",
            "destination_origin_sha256",
            "destination_path_or_prefix",
            "destination_operator_class",
            "egress_policy_sha256",
            "cross_origin_redirect_allowed",
            "unbound_proxy_route_allowed",
        )
    }
    validate_destination_authority_v1(
        destination_authority,
        destination=destination,
        egress_policy_sha256=str(egress["egress_policy_sha256"]),
    )
    dispatcher = environment.dispatcher_for(
        approval_id,
        approved_destination_authority=destination_authority,
    )
    nonce_store = DestinationBoundNonceStoreV2Adapter(
        delegate=environment.nonce_store(),
        destination=destination,
        approval=approval,
    )
    output_root = dispatcher.execution_root / "output"
    try:
        result = await pilot.launch_one_sealed_sample(
            repo_root=environment.repo_root,
            pilot_id=pilot.PILOT_ID,
            sample_id=str(lock["sample_id"]),
            expected_sample_lock_sha256=str(lock["sample_lock_sha256"]),
            expected_parent_experiment_lock_sha256=pilot.PARENT_EXPERIMENT_LOCK_SHA256,
            permission=permission,
            signed_approval=approval,
            nonce_store=nonce_store,
            ledger=pilot.FakePilotLedger(),
            dispatcher=dispatcher,
            output_root=output_root,
            offline_fake=False,
        )
    except BaseException as exc:
        receipt_sha = hashlib.sha256(
            json.dumps(
                {"status": "FAILED", "reason_code": getattr(exc, "reason_code", "UNEXPECTED")},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        try:
            nonce_store.load(
                pilot_id=pilot.PILOT_ID,
                sample_id=str(lock["sample_id"]),
                approval_id=approval_id,
            )
        except Exception:
            pass
        else:
            approvals.consume_successor_signed_approval_v1(
                store_root=environment.approval_store_root,
                approval_id=approval_id,
                execution_receipt_sha256=receipt_sha,
            )
        raise
    receipt_sha = hashlib.sha256(
        json.dumps(result, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    approvals.consume_successor_signed_approval_v1(
        store_root=environment.approval_store_root,
        approval_id=approval_id,
        execution_receipt_sha256=receipt_sha,
    )
    return result
