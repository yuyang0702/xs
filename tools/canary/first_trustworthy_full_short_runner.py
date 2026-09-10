"""Exact one-shot Full Short preflight and authorized execution entry.

The default mode is preflight-only and cannot construct a secret store,
provider client, approval, nonce, or network request.  ``--execute`` is the
only real boundary.  It is intended to be invoked only after the user freshly
activates the exact canonical authorization SHA-256 produced after the final
Git HEAD is frozen.
"""

from __future__ import annotations

import argparse
import asyncio
import ast
from datetime import datetime, timezone
import hashlib
import inspect
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit

from novel_flywheel.config import Settings, configure_runtime_environment
from novel_flywheel.db import Database
from novel_flywheel.execution_failure_architecture import (
    AuthorityEffect,
    DURABLE_FAILURE_EVIDENCE_POLICY_SHA256,
    DURABLE_FAILURE_EVIDENCE_POLICY_V1,
    DispatchState,
    ExecutionBoundaryFailure,
    FAILURE_ARCHITECTURE_IDENTITY,
    FailureLayer,
    FULL_SHORT_EXACT_RECOVERY_REGISTRY_SHA256,
    FULL_SHORT_EXACT_RECOVERY_REGISTRY_V1,
    NONCE_RESERVATION_POLICY_SHA256,
    NONCE_RESERVATION_POLICY_V1,
    OBSERVER_ISOLATION_POLICY_SHA256,
    OBSERVER_ISOLATION_POLICY_V1,
    PREDISPATCH_STATE_MACHINE_SHA256,
    PREDISPATCH_STATE_MACHINE_V1,
    RestartBehavior,
    build_durable_failure_evidence,
)
from novel_flywheel.external_workload_evidence import (
    ExpectedWorkloadEvidenceV1,
    ExternalWorkloadEvidenceError,
    VerifiedWorkloadEvidenceV1,
    validate_external_workload_evidence_v1,
)
from novel_flywheel.full_short_execution import (
    FullShortDispatchLedgerObserverV1,
    FullShortDurableExecutionStoreV1,
    FullShortExecutionBoundaryError,
    LOGICAL_STAGE_RECOVERY_POLICY_SHA256,
    LOGICAL_STAGE_RECOVERY_POLICY_V1,
    RESPONSE_CAPTURE_POLICY_SHA256,
    RESPONSE_CAPTURE_POLICY_V1,
    TRANSPORT_RECOVERY_POLICY_SHA256,
    TRANSPORT_RECOVERY_POLICY_V1,
    build_full_short_completion_receipt_v1,
    full_short_logical_stage_plan_sha256_v1,
    full_short_workload_request_family_sha256_v1,
    validate_full_short_logical_stage_plan_v1,
    validate_full_short_canonical_authorization_v1,
    validate_full_short_preflight_v1,
)
from novel_flywheel.full_short_probe_campaign import ProbeCase, ProbeRouteIdentity
from novel_flywheel.full_short_runtime_kernel import (
    DEFAULT_FAILURE_BOUNDARY_REGISTRY_V1,
    DurableExecutionJournalV1,
    ExecutionState,
    FullShortExecutionKernel,
    FullShortRestartReconcilerV1,
    activate_full_short_kernel_v1,
)
from novel_flywheel.models import ModelGateway
from novel_flywheel.nlp_backend import LocalNLPManager
from novel_flywheel.projects import ProjectStore
from novel_flywheel.providers.http import SingleDispatchTransportPolicyV1
from novel_flywheel.providers.registry import ProviderRegistry
from novel_flywheel.prompts import OPTIONAL_PROMPT_SKILLS, REQUIRED_SKILLS
from novel_flywheel.quality_profiles import profile_for_project
from novel_flywheel.reference_library import ReferenceLibrary
from novel_flywheel.recovery_engine import FailureClass
from novel_flywheel.route_capabilities import (
    RouteCapabilityError,
    RouteCapabilityRecordV1,
    RouteCapabilityRegistryV1,
)
from novel_flywheel.runtime_fingerprint import collect_runtime_fingerprint_v2
from novel_flywheel.secrets import KeyringSecretStore, MemorySecretStore
from novel_flywheel.short_canonical_promotion import (
    short_canonical_feature_snapshot,
)
from novel_flywheel.skills import SkillGate, SkillScanner
from novel_flywheel.skill_prompts import (
    ConstraintPromptCompactor,
    SkillPromptCompactor,
)
from novel_flywheel.story_state import StoryStateStore
from novel_flywheel.stage_capacity import (
    CapacityAdmissionFailureV1,
    CapacityFailureCode,
    DEFAULT_STAGE_CAPACITY_POLICY_REGISTRY_V1,
    MAX_CONTEXT_LIMIT_TOKENS_V1,
    _issue_verified_external_workload_capacity_issuer_v1,
)
from novel_flywheel.style_context import selected_style_reference_provenance
from novel_flywheel.tasks import RunTaskManager
from novel_flywheel.workflows import WorkflowService
from tools.canary.short_completion import COMPLETION_GOAL
from tools.canary.short_completion_verification import verify_short_completion_v1


FULL_SHORT_BOUND_ROLES = (
    "planning", "draft", "review", "reader_review", "polish",
    "final_review", "maintenance", "revision_plan",
)

_OFFLINE_CONTEXT_MANIFEST_KEY_V1 = (
    "offline_deterministic_context_manifest_v1"
)
_OFFLINE_CONTEXT_MANIFEST_SCHEMA_V1 = (
    "OfflineDeterministicGatewayContextCapabilityManifestV1"
)
_ROUTE_CAPABILITY_REGISTRY_PATH_V1 = Path(
    "config/full_short_route_capability_registry_v1.json"
)


def _route_context_capability_v1(
    model: dict[str, Any],
    *,
    capability_record: RouteCapabilityRecordV1 | None = None,
    route_fingerprint: str | None = None,
) -> tuple[int, str]:
    """Return a source-grounded route limit without inventing a fallback."""

    configured_context = model.get("context_window")
    capabilities = model.get("capabilities")
    manifest = (
        capabilities.get(_OFFLINE_CONTEXT_MANIFEST_KEY_V1)
        if isinstance(capabilities, dict)
        else None
    )
    if manifest is None:
        if capability_record is None:
            raise CapacityAdmissionFailureV1(
                CapacityFailureCode.ROUTE_CAPABILITY_UNKNOWN
            )
        try:
            capability_record.require_dispatchable()
        except RouteCapabilityError as exc:
            raise CapacityAdmissionFailureV1(
                CapacityFailureCode.ROUTE_CAPABILITY_UNKNOWN
            ) from exc
        if capability_record.route_fingerprint != route_fingerprint:
            raise CapacityAdmissionFailureV1(
                CapacityFailureCode.ROUTE_CAPABILITY_UNKNOWN
            )
        assert capability_record.context_window_tokens is not None
        return (
            capability_record.context_window_tokens,
            "route_capability_registry",
        )
    expected_manifest = {
        "schema": _OFFLINE_CONTEXT_MANIFEST_SCHEMA_V1,
        "version": 1,
        "context_limit_tokens": configured_context,
        "capacity_policy_registry_sha256": (
            DEFAULT_STAGE_CAPACITY_POLICY_REGISTRY_V1.identity_sha256
        ),
        "scope": "ISOLATED_PRIVATE_DATA_COPY_ONLY",
        "external_actions_enabled": False,
    }
    if (
        type(configured_context) is not int
        or configured_context <= 0
        or type(manifest) is not dict
        or manifest != expected_manifest
    ):
        raise CapacityAdmissionFailureV1(
            CapacityFailureCode.CONTEXT_LIMIT_INCONSISTENT
        )
    return configured_context, "offline_deterministic_gateway_manifest"


def _load_route_capability_registry_v1(
    repo: Path,
) -> RouteCapabilityRegistryV1 | None:
    path = repo / _ROUTE_CAPABILITY_REGISTRY_PATH_V1
    if not path.is_file():
        return None
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("route capability registry document invalid")
    registry = RouteCapabilityRegistryV1.from_document(document)
    repo_root = repo.resolve(strict=True)

    def resolve_locator(value: Any, fragment: str) -> Any:
        if not fragment:
            return value
        current = value
        for raw_part in fragment.lstrip("/").split("/"):
            part = raw_part.replace("~1", "/").replace("~0", "~")
            if isinstance(current, dict) and part in current:
                current = current[part]
            elif isinstance(current, list) and part.isdigit():
                index = int(part)
                if index >= len(current):
                    raise ValueError(
                        "route capability evidence locator missing"
                    )
                current = current[index]
            else:
                raise ValueError("route capability evidence locator missing")
        return current

    for record in registry.records:
        verified = record.capability_status.value.startswith("VERIFIED_")
        expected_values = {
            "context_window_tokens": record.context_window_tokens,
            "max_output_tokens": record.max_output_tokens,
            "reasoning_token_accounting": (
                record.reasoning_token_accounting
            ),
            "reasoning_output_reservation": (
                record.reasoning_output_reservation
            ),
            "route_fingerprint": record.route_fingerprint,
            "provider": record.provider,
            "provider_id_sha256": record.provider_id_sha256,
            "operator": record.operator,
            "destination": record.destination,
            "protocol": record.protocol,
            "model": record.model,
            "model_id_sha256": record.model_id_sha256,
        }
        if record.reasoning_token_accounting == "SEPARATE_IF_REPORTED":
            expected_values["reasoning_token_reserve"] = (
                record.reasoning_token_reserve
            )
        route_identity_fields = {
            "route_fingerprint", "provider", "provider_id_sha256",
            "operator", "destination", "protocol", "model",
            "model_id_sha256",
        }
        semantically_proved: set[str] = set()
        for evidence in record.source_evidence:
            if not evidence.provenance_available:
                continue
            locator_parts = evidence.source_locator.split("#", 1)
            relative = locator_parts[0]
            fragment = locator_parts[1] if len(locator_parts) == 2 else ""
            source = (repo_root / relative).resolve(strict=False)
            try:
                source.relative_to(repo_root)
            except ValueError as exc:
                raise ValueError(
                    "route capability evidence escapes repository"
                ) from exc
            if (
                not source.is_file()
                or _sha256(source) != evidence.source_evidence_sha256
            ):
                raise ValueError("route capability evidence hash mismatch")
            try:
                source_document = json.loads(
                    source.read_text(encoding="utf-8")
                )
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError(
                    "verified route capability evidence must be JSON"
                ) from exc
            located = resolve_locator(source_document, fragment)
            if not verified:
                continue
            # One evidence locator must name one route-exact assertion.  Never
            # assemble a VERIFIED record by recursively picking matching
            # fields from unrelated objects in the same JSON subtree.
            proved_fields = {
                field for field in evidence.proved_fields
                if field in expected_values
            }
            required_fields = proved_fields | route_identity_fields
            if (
                isinstance(located, dict)
                and all(
                    field in located
                    and located[field] == expected_values[field]
                    for field in required_fields
                )
            ):
                semantically_proved.update(proved_fields)
        if verified and semantically_proved != set(expected_values):
            raise ValueError(
                "verified route capability evidence values not proven"
            )
    return registry


def _route_operator_v1(
    *, provider_id: str, provider: dict[str, Any], destination: str,
) -> str:
    if (
        provider_id == "0e6a5627-5882-40df-bca5-7d98b97fdd0b"
        and str(provider.get("name") or "").strip().casefold() == "deepseek"
        and destination
        == "https://api.deepseek.com:443/anthropic/v1/messages"
        and str(provider.get("protocol")) == "anthropic"
    ):
        return "DEEPSEEK_OFFICIAL"
    if (
        destination
        == "https://ark.cn-beijing.volces.com:443/api/v3/responses"
        and str(provider.get("protocol")) == "openai-responses"
    ):
        return "VOLCENGINE_ARK_DIRECT"
    return "THIRD_PARTY_RELAY_UNVERIFIED_UPSTREAM"
FULL_SHORT_REQUIRED_EXECUTION_ROLES = (
    "planning", "draft", "review", "reader_review", "polish",
    "final_review", "maintenance",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _domain(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _safe_failure_metadata(exc: BaseException, *, boundary: str) -> dict[str, Any]:
    candidate = exc
    if getattr(candidate, "reliability_failure", None) is None:
        preflight = "preflight" in boundary
        wrapped = ExecutionBoundaryFailure(
            (
                "preflight_validation_failed"
                if preflight else "typed_local_boundary_failure"
            ),
            layer=(
                FailureLayer.EXECUTION_AUTHORIZATION
                if preflight else FailureLayer.WORKFLOW_RECOVERY
            ),
            boundary=boundary,
            failure_class=(
                FailureClass.STALE_AUTHORITY
                if preflight else FailureClass.SEMANTIC_INVARIANT
            ),
            dispatch_state=DispatchState.NOT_REACHED,
            authority_effect=AuthorityEffect.BLOCKS_ACCEPTANCE,
            restart_behavior=(
                RestartBehavior.FRESH_AUTHORIZATION_REQUIRED
                if preflight else RestartBehavior.NO_REDISPATCH
            ),
            recovery_action=(
                "correct_binding_then_materialize_fresh_authorization"
                if preflight else "inspect_typed_local_failure"
            ),
        )
        wrapped.__cause__ = candidate
        candidate = wrapped
    return build_durable_failure_evidence(
        candidate, boundary=boundary,
    ).event_metadata()


def _supervised_run_not_completed_failure(
    diagnostic: dict[str, Any],
    workflow_exception: BaseException | None,
) -> FullShortExecutionBoundaryError:
    """Retain the in-memory child cause while exposing only safe diagnostics."""

    failure = FullShortExecutionBoundaryError(
        "FULL_SHORT_SUPERVISED_RUN_NOT_COMPLETED"
    )
    failure.safe_diagnostic = diagnostic
    if workflow_exception is not None:
        failure.__cause__ = workflow_exception
    return failure


def _persist_preflight_failure(
    args: argparse.Namespace, exc: BaseException, *,
    boundary: str = "full_short.preflight",
    approval_created: bool = False,
    nonce_created: bool = False,
) -> dict[str, Any]:
    """Persist a secret-free failure graph without approval/nonce creation."""

    metadata = _safe_failure_metadata(
        exc, boundary=boundary,
    )
    receipt = {
        "schema": "FullShortPreflightFailureReceiptV1", "version": 1,
        **metadata,
        "approval_created": approval_created,
        "nonce_created": nonce_created,
        "credential_lookup_count": 0, "network_calls": 0,
    }
    root = Path(args.store_root).resolve(strict=False)
    root.mkdir(parents=True, exist_ok=True)
    path = root / (
        "preflight-failure-" + metadata["failure_graph_sha256"] + ".json"
    )
    raw = json.dumps(
        receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8") + b"\n"
    try:
        with path.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        if path.read_bytes() != raw:
            raise FullShortExecutionBoundaryError(
                "PREFLIGHT_FAILURE_RECEIPT_COLLISION"
            )
    return {**receipt, "path": str(path)}


def _terminalize_prelaunch_failure(
    args: argparse.Namespace,
    exc: Exception,
    *,
    boundary: str,
    manager: RunTaskManager,
    execution_id: str,
    approval_created: bool,
) -> None:
    """Terminalize exact-once state even when receipt media is unavailable."""

    persistence_error: Exception | None = None
    try:
        failure = _persist_preflight_failure(
            args, exc, boundary=boundary,
            approval_created=approval_created,
        )
    except Exception as receipt_exc:
        persistence_error = receipt_exc
        failure = _safe_failure_metadata(exc, boundary=boundary)
    reason_code = (
        "FULL_SHORT_PRELAUNCH_FAILURE_GRAPH_"
        + failure["failure_graph_sha256"]
    )
    if not manager.fail_closed_exact_once_reservation(
        execution_id, reason_code=reason_code,
    ):
        raise FullShortExecutionBoundaryError(
            "FULL_SHORT_PRELAUNCH_RESERVATION_CLEANUP_FAILED"
        )
    if persistence_error is not None:
        exc.add_note(
            "preflight failure receipt persistence also failed: "
            + type(persistence_error).__name__
        )


def _canonical_store_root(
    *, repo: Path, data_dir: Path, store_root: Path | None,
) -> Path:
    """Resolve the exact control-plane store identity without creating it."""

    requested = (
        store_root
        if store_root is not None
        else data_dir.parent / "full-short-execution-store"
    )
    exact = Path(os.path.abspath(requested)).resolve(strict=False)
    try:
        exact.relative_to(repo.resolve(strict=True))
    except ValueError:
        return exact
    raise ValueError("full short store root must be outside the Git worktree")


def _workflow_cutover_source_truth() -> dict[str, Any]:
    """Derive retired-cutover reachability from executable Python source."""

    workflow_path = Path(inspect.getfile(WorkflowService)).resolve(strict=True)
    source = workflow_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(workflow_path))
    planning_v2_imports: list[str] = []
    planning_v2_calls: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            planning_v2_imports.extend(
                item.name for item in node.names
                if "planning_v2_slice1" in item.name
            )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if "planning_v2_slice1" in module:
                planning_v2_imports.extend(
                    f"{module}.{item.name}" for item in node.names
                )
        elif isinstance(node, ast.Call):
            try:
                rendered = ast.unparse(node.func)
            except Exception:
                rendered = ""
            if "planning_v2_slice1" in rendered:
                planning_v2_calls.append(rendered)
    hybrid_default = inspect.signature(WorkflowService.__init__).parameters[
        "hybrid_skill_context_shadow_enabled"
    ].default
    if type(hybrid_default) is not bool:
        raise ValueError("hybrid Skill context default is not a sealed boolean")
    source_truth = {
        "schema": "FullShortCutoverSourceTruthV1",
        "version": 1,
        "workflow_source_sha256": _sha256(workflow_path),
        "hybrid_skill_context_shadow_default_enabled": hybrid_default,
        "runner_hybrid_skill_context_shadow_override_enabled": False,
        "planning_v2_runtime_imports": sorted(set(planning_v2_imports)),
        "planning_v2_runtime_calls": sorted(set(planning_v2_calls)),
        "derivation": "python_ast_and_constructor_signature",
    }
    return {
        **source_truth,
        "source_truth_sha256": _domain(source_truth),
        "skill_v3_production_cutover": bool(hybrid_default),
        "planning_v2_production_cutover": bool(
            planning_v2_imports or planning_v2_calls
        ),
    }


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=repo, text=True, encoding="utf-8",
    ).strip()


def _destination(provider: dict) -> str:
    base = str(provider["base_url"]).rstrip("/")
    protocol = str(provider["protocol"])
    if protocol == "anthropic":
        url = f"{base}/{'messages' if base.endswith('/v1') else 'v1/messages'}"
    elif protocol == "openai-chat":
        url = f"{base}/chat/completions"
    elif protocol == "openai-responses":
        url = f"{base}/responses"
    else:
        raise ValueError("unsupported route protocol")
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("full short destination must be exact HTTPS")
    return f"{parsed.scheme}://{parsed.hostname}:{parsed.port or 443}{parsed.path}"


_EXTERNAL_AUTHORIZED_CASE_KEYS_V1 = {
    "blocked_shape_ordinals", "case_id", "case_sha256",
    "estimated_input_tokens", "fixture_sha256", "input_envelope_sha256",
    "ordinal", "request_family_sha256", "request_sha256", "route",
    "wire_requested_output_cap",
}
_EXTERNAL_AUTHORIZED_ROUTE_KEYS_V1 = {
    "destination", "destination_sha256", "model", "operator", "protocol",
    "provider", "route_fingerprint",
}


def _is_lower_hex(value: Any, length: int) -> bool:
    return (
        isinstance(value, str)
        and len(value) == length
        and all(character in "0123456789abcdef" for character in value)
    )


def _validate_authorized_external_workload_evidence_v1(
    *,
    evidence: tuple[VerifiedWorkloadEvidenceV1, ...],
    authorized_cases: tuple[Mapping[str, Any], ...],
    authorization_sha256: str,
    final_execution_head: str,
    verification_keys: Mapping[str, bytes],
) -> None:
    """Reverify evidence only against the caller's frozen outer manifest.

    In particular, no expected field is copied from an evidence value.  The
    only evidence-owned values consulted before package verification are the
    case identity used to select an outer-authorized case and the immutable
    package bytes themselves.
    """

    if (
        not isinstance(evidence, tuple)
        or not evidence
        or not all(isinstance(item, VerifiedWorkloadEvidenceV1) for item in evidence)
        or not isinstance(authorized_cases, tuple)
        or len(authorized_cases) != len(evidence)
        or not _is_lower_hex(authorization_sha256, 64)
        or not _is_lower_hex(final_execution_head, 40)
        or not isinstance(verification_keys, Mapping)
        or len(verification_keys) != 1
    ):
        raise CapacityAdmissionFailureV1(
            CapacityFailureCode.ROUTE_CAPABILITY_UNKNOWN
        )
    key_id, key = next(iter(verification_keys.items()))
    if (
        not isinstance(key_id, str)
        or not key_id
        or key_id.strip() != key_id
        or not isinstance(key, bytes)
        or len(key) < 32
    ):
        raise CapacityAdmissionFailureV1(
            CapacityFailureCode.ROUTE_CAPABILITY_UNKNOWN
        )

    expected_by_case: dict[str, ExpectedWorkloadEvidenceV1] = {}
    for ordinal, case in enumerate(authorized_cases, 1):
        if (
            not isinstance(case, Mapping)
            or set(case) not in (_EXTERNAL_AUTHORIZED_CASE_KEYS_V1,
                _EXTERNAL_AUTHORIZED_CASE_KEYS_V1 | {"historical_admission_sha256"})
            or case.get("ordinal") != ordinal
            or not isinstance(case.get("route"), Mapping)
            or set(case["route"]) != _EXTERNAL_AUTHORIZED_ROUTE_KEYS_V1
        ):
            raise CapacityAdmissionFailureV1(
                CapacityFailureCode.ROUTE_CAPABILITY_UNKNOWN
            )
        route = case["route"]
        case_id = case.get("case_id")
        input_tokens = case.get("estimated_input_tokens")
        requested_output_tokens = case.get("wire_requested_output_cap")
        blocked_shape_ordinals = case.get("blocked_shape_ordinals")
        if (
            not isinstance(case_id, str)
            or not case_id
            or case_id.strip() != case_id
            or case_id in expected_by_case
            or not isinstance(input_tokens, int)
            or isinstance(input_tokens, bool)
            or input_tokens <= 0
            or not isinstance(requested_output_tokens, int)
            or isinstance(requested_output_tokens, bool)
            or requested_output_tokens <= 0
            or requested_output_tokens > 32_000
            or not isinstance(blocked_shape_ordinals, list)
            or not blocked_shape_ordinals
            or any(
                not isinstance(value, int)
                or isinstance(value, bool)
                or value <= 0
                for value in blocked_shape_ordinals
            )
            or blocked_shape_ordinals != sorted(set(blocked_shape_ordinals))
            or case.get("input_envelope_sha256") != case.get("request_sha256")
            or not _is_lower_hex(case.get("fixture_sha256"), 64)
            or not _is_lower_hex(case.get("request_family_sha256"), 64)
            or not _is_lower_hex(case.get("request_sha256"), 64)
            or not _is_lower_hex(route.get("destination_sha256"), 64)
            or not _is_lower_hex(route.get("route_fingerprint"), 64)
            or hashlib.sha256(
                str(route.get("destination") or "").encode("utf-8")
            ).hexdigest() != route.get("destination_sha256")
            or any(
                not isinstance(route.get(name), str)
                or not route[name]
                or route[name].strip() != route[name]
                for name in (
                    "provider", "operator", "destination", "protocol", "model"
                )
            )
        ):
            raise CapacityAdmissionFailureV1(
                CapacityFailureCode.ROUTE_CAPABILITY_UNKNOWN
            )
        try:
            runtime_case = ProbeCase(
                ordinal=ordinal,
                case_id=case_id,
                route=ProbeRouteIdentity(
                    provider=route["provider"],
                    operator=route["operator"],
                    destination_sha256=route["destination_sha256"],
                    protocol=route["protocol"],
                    model=route["model"],
                    route_fingerprint=route["route_fingerprint"],
                ),
                fixture_sha256=case["fixture_sha256"],
                input_envelope_sha256=case["input_envelope_sha256"],
                estimated_input_tokens=input_tokens,
                wire_requested_output_cap=requested_output_tokens,
                blocked_shape_ordinals=tuple(blocked_shape_ordinals),
            )
        except (TypeError, ValueError, RuntimeError):
            raise CapacityAdmissionFailureV1(
                CapacityFailureCode.ROUTE_CAPABILITY_UNKNOWN
            ) from None
        if runtime_case.case_sha256 != case.get("case_sha256"):
            raise CapacityAdmissionFailureV1(
                CapacityFailureCode.ROUTE_CAPABILITY_UNKNOWN
            )
        expected_by_case[case_id] = ExpectedWorkloadEvidenceV1(
            authorization_sha256=authorization_sha256,
            final_execution_head=final_execution_head,
            provider=route["provider"],
            operator=route["operator"],
            destination=route["destination"],
            protocol=route["protocol"],
            model=route["model"],
            route_fingerprint_sha256=route["route_fingerprint"],
            case_id=case_id,
            fixture_sha256=case["fixture_sha256"],
            request_family_sha256=case["request_family_sha256"],
            request_sha256=case["request_sha256"],
            input_tokens=input_tokens,
            requested_output_tokens=requested_output_tokens,
            key_id=key_id,
            historical_admission_sha256=case.get("historical_admission_sha256"),
        )

    observed_case_ids: set[str] = set()
    observed_nonce_sha256s: set[str] = set()
    observed_evidence_sha256s: set[str] = set()
    for item in evidence:
        expected = expected_by_case.get(item.case_id)
        if expected is None or item.case_id in observed_case_ids:
            raise CapacityAdmissionFailureV1(
                CapacityFailureCode.ROUTE_CAPABILITY_UNKNOWN
            )
        try:
            reverified = validate_external_workload_evidence_v1(
                item.package_bytes,
                expected=expected,
                verification_keys=verification_keys,
            )
        except ExternalWorkloadEvidenceError:
            raise CapacityAdmissionFailureV1(
                CapacityFailureCode.ROUTE_CAPABILITY_UNKNOWN
            ) from None
        if (
            reverified != item
            or item.nonce_sha256 in observed_nonce_sha256s
            or item.evidence_sha256 in observed_evidence_sha256s
        ):
            raise CapacityAdmissionFailureV1(
                CapacityFailureCode.ROUTE_CAPABILITY_UNKNOWN
            )
        observed_case_ids.add(item.case_id)
        observed_nonce_sha256s.add(item.nonce_sha256)
        observed_evidence_sha256s.add(item.evidence_sha256)
    if observed_case_ids != set(expected_by_case):
        raise CapacityAdmissionFailureV1(
            CapacityFailureCode.ROUTE_CAPABILITY_UNKNOWN
        )


def collect_live_bindings(
    *, repo: Path, data_dir: Path, project_id: str, run_id: str,
    logical_stage_plan: list[dict[str, Any]], store_root: Path | None = None,
    verified_external_workload_evidence: tuple[
        VerifiedWorkloadEvidenceV1, ...
    ] = (),
    external_workload_authorized_cases: tuple[Mapping[str, Any], ...] = (),
    external_workload_authorization_sha256: str | None = None,
    external_workload_verification_keys: Mapping[str, bytes] | None = None,
    outer_authorization_projection: bool = False,
) -> tuple[dict, dict]:
    """Collect public, credential-free live bindings from source truth."""

    logical_stage_plan = validate_full_short_logical_stage_plan_v1(
        logical_stage_plan,
    )
    logical_stage_plan_sha256 = full_short_logical_stage_plan_sha256_v1(
        logical_stage_plan,
    )
    repo = repo.resolve(strict=True)
    data_dir = data_dir.resolve(strict=True)
    exact_store_root = _canonical_store_root(
        repo=repo, data_dir=data_dir, store_root=store_root,
    )
    execution_head = _git(repo, "rev-parse", "HEAD")
    if type(outer_authorization_projection) is not bool:
        raise CapacityAdmissionFailureV1(
            CapacityFailureCode.ROUTE_CAPABILITY_UNKNOWN
        )
    if outer_authorization_projection and (
        verified_external_workload_evidence
        or external_workload_authorized_cases
        or external_workload_authorization_sha256 is not None
        or external_workload_verification_keys is not None
    ):
        raise CapacityAdmissionFailureV1(
            CapacityFailureCode.ROUTE_CAPABILITY_UNKNOWN
        )
    if verified_external_workload_evidence:
        if (
            not isinstance(external_workload_authorization_sha256, str)
            or not isinstance(external_workload_verification_keys, Mapping)
        ):
            raise CapacityAdmissionFailureV1(
                CapacityFailureCode.ROUTE_CAPABILITY_UNKNOWN
            )
        _validate_authorized_external_workload_evidence_v1(
            evidence=verified_external_workload_evidence,
            authorized_cases=external_workload_authorized_cases,
            authorization_sha256=external_workload_authorization_sha256,
            final_execution_head=execution_head,
            verification_keys=external_workload_verification_keys,
        )
    elif (
        external_workload_authorized_cases
        or external_workload_authorization_sha256 is not None
        or external_workload_verification_keys is not None
    ):
        raise CapacityAdmissionFailureV1(
            CapacityFailureCode.ROUTE_CAPABILITY_UNKNOWN
        )
    used_external_evidence_sha256s: set[str] = set()
    attestation_store = FullShortDurableExecutionStoreV1(
        repo_root=repo, store_root=exact_store_root,
    )
    db = Database(data_dir / "app.db")
    project_row = db.get_project(project_id)
    if project_row is None:
        raise ValueError("project not found")
    project_root = Path(str(project_row["path"])).resolve(strict=True)
    if not project_root.is_relative_to((data_dir / "projects").resolve()):
        raise ValueError("project is outside the bound data directory")
    projects = ProjectStore(db, data_dir / "projects")
    project = projects.get(project_id)
    project_document = json.loads(
        (project_root / "project.json").read_text(encoding="utf-8"),
    )
    if str(project_document.get("id")) != project_id:
        raise ValueError("project identity drift")
    state = StoryStateStore(db).get(project_id)
    if state is None:
        raise ValueError("StoryState authority is not initialized")

    records: list[dict] = []
    destinations: set[str] = set()
    max_per_call = 0
    capability_registry = _load_route_capability_registry_v1(repo)
    selected_route_output_caps: dict[tuple[str, str], int] = {}
    for item in logical_stage_plan:
        route_key = (
            str(item["role"]),
            "fallback"
            if item["route_lane"] == "configured_fallback"
            else str(item["route_lane"]),
        )
        selected_route_output_caps[route_key] = max(
            selected_route_output_caps.get(route_key, 0),
            int(item["requested_output_tokens"]),
        )
    selected_routes = set(selected_route_output_caps)
    for role in FULL_SHORT_BOUND_ROLES:
        binding = db.get_role_binding(role) or {}
        for lane in ("primary", "fallback"):
            provider_id = binding.get(f"{lane}_provider_id")
            model_id = binding.get(f"{lane}_model_id")
            if (role, lane) in selected_routes and not (
                provider_id and model_id
            ):
                raise ValueError("required Full Short plan route is missing")
            if not provider_id or not model_id:
                continue
            provider = db.get_provider(str(provider_id))
            model = db.get_model(str(model_id))
            if not provider or not model or not provider.get("enabled"):
                raise ValueError("route binding is incomplete or disabled")
            destination = _destination(provider)
            destinations.add(destination)
            configured_max = model.get("max_output_tokens")
            route_fingerprint = ProviderRegistry.route_fingerprint(
                provider, model,
            )
            provider_id_sha256 = hashlib.sha256(
                str(provider_id).encode("utf-8")
            ).hexdigest()
            model_id_sha256 = hashlib.sha256(
                str(model_id).encode("utf-8")
            ).hexdigest()
            operator = _route_operator_v1(
                provider_id=str(provider_id), provider=provider,
                destination=destination,
            )
            route_selected = (role, lane) in selected_routes
            route_plan_entries = [
                entry for entry in logical_stage_plan
                if entry["role"] == role
                and (
                    "fallback"
                    if entry["route_lane"] == "configured_fallback"
                    else entry["route_lane"]
                ) == lane
            ]
            capabilities = model.get("capabilities")
            offline_manifest = (
                capabilities.get(_OFFLINE_CONTEXT_MANIFEST_KEY_V1)
                if isinstance(capabilities, dict)
                else None
            )
            capability_record = None
            if offline_manifest is None:
                if capability_registry is None:
                    raise CapacityAdmissionFailureV1(
                        CapacityFailureCode.ROUTE_CAPABILITY_UNKNOWN
                    )
                try:
                    capability_record = capability_registry.require_record(
                        role=role, lane=lane,
                    )
                    capability_record.require_exact_route_identity(
                        role=role,
                        lane=lane,
                        provider=str(provider.get("name") or ""),
                        provider_id_sha256=provider_id_sha256,
                        operator=operator,
                        destination=destination,
                        protocol=str(provider["protocol"]),
                        model=str(model.get("model_name") or ""),
                        model_id_sha256=model_id_sha256,
                        route_fingerprint=route_fingerprint,
                    )
                except RouteCapabilityError as exc:
                    raise CapacityAdmissionFailureV1(
                        CapacityFailureCode.ROUTE_CAPABILITY_UNKNOWN
                    ) from exc
            stage_budget_role = "review" if role == "reader_review" else role
            stage_output_budget = WorkflowService._stage_output_budget(
                stage_budget_role
            )
            external_families: list[dict[str, Any]] = []
            if (
                capability_record is not None
                and route_selected
                and not capability_record.capability_status.value.startswith(
                    "VERIFIED_"
                )
            ):
                if not verified_external_workload_evidence:
                    if outer_authorization_projection:
                        route_context_limit = None
                        route_context_source = None
                        max_output = None
                        max_output_source = None
                    else:
                        raise CapacityAdmissionFailureV1(
                            CapacityFailureCode.ROUTE_CAPABILITY_UNKNOWN
                        )
                else:
                    for plan_entry in route_plan_entries:
                        family_sha256 = full_short_workload_request_family_sha256_v1(
                            plan_entry,
                            provider=str(provider.get("name") or ""),
                            operator=operator,
                            destination=destination,
                            protocol=str(provider["protocol"]),
                            model=str(model.get("model_name") or ""),
                            route_fingerprint_sha256=route_fingerprint,
                        )
                        candidates = [
                            item for item in verified_external_workload_evidence
                            if item.request_family_sha256 == family_sha256
                            and item.capacity_authorization_sha256
                            == external_workload_authorization_sha256
                            and item.capacity_execution_head == execution_head
                            and item.provider == str(provider.get("name") or "")
                            and item.operator == operator
                            and item.destination == destination
                            and item.protocol == str(provider["protocol"])
                            and item.model == str(model.get("model_name") or "")
                            and item.route_fingerprint_sha256 == route_fingerprint
                        ]
                        if len(candidates) != 1:
                            raise CapacityAdmissionFailureV1(
                                CapacityFailureCode.ROUTE_CAPABILITY_UNKNOWN
                            )
                        evidence = candidates[0]
                        if (
                            plan_entry["requested_output_tokens"]
                            > evidence.requested_output_tokens
                            or evidence.input_tokens
                            + evidence.requested_output_tokens
                            > MAX_CONTEXT_LIMIT_TOKENS_V1
                        ):
                            raise CapacityAdmissionFailureV1(
                                CapacityFailureCode.OUTPUT_RESERVE_UNSATISFIED
                            )
                        used_external_evidence_sha256s.add(evidence.evidence_sha256)
                        family = {
                            "schema": "VerifiedExternalWorkloadFamilyV1",
                            "version": 1,
                            "request_family_sha256": family_sha256,
                            "request_sha256": evidence.request_sha256,
                            "evidence_sha256": evidence.evidence_sha256,
                            "authorization_sha256": evidence.capacity_authorization_sha256,
                            "final_execution_head": evidence.capacity_execution_head,
                            "case_id": evidence.case_id,
                            "input_tokens": evidence.input_tokens,
                            "requested_output_tokens": evidence.requested_output_tokens,
                            "actual_output_tokens": evidence.actual_output_tokens,
                            "proven_workload_context_lower_bound_tokens": (
                                evidence.input_tokens
                                + evidence.requested_output_tokens
                            ),
                        }
                        if evidence.historical_admission_sha256 is not None:
                            family.update(schema="HistoricalVerifiedExternalWorkloadFamilyV1",
                                source_authorization_sha256=evidence.authorization_sha256,
                                source_execution_head=evidence.final_execution_head,
                                source_nonce_sha256=evidence.nonce_sha256,
                                historical_admission_sha256=evidence.historical_admission_sha256)
                        if family not in external_families:
                            external_families.append(family)
                    external_families.sort(
                        key=lambda item: item["request_family_sha256"]
                    )
                    route_context_limit = min(
                        item["proven_workload_context_lower_bound_tokens"]
                        for item in external_families
                    )
                    route_context_source = "verified_external_workload_evidence"
                    max_output = min(
                        item["requested_output_tokens"]
                        for item in external_families
                    )
                    max_output_source = "verified_external_workload_evidence"
            elif capability_record is not None and (
                route_selected
                or capability_record.capability_status.value.startswith(
                    "VERIFIED_"
                )
            ):
                if route_selected:
                    route_context_limit, route_context_source = (
                        _route_context_capability_v1(
                            model,
                            capability_record=capability_record,
                            route_fingerprint=route_fingerprint,
                        )
                    )
                else:
                    route_context_limit = (
                        capability_record.context_window_tokens
                    )
                    route_context_source = "route_capability_registry"
                assert capability_record.max_output_tokens is not None
                if (
                    type(configured_max) is int
                    and configured_max > capability_record.max_output_tokens
                ):
                    raise CapacityAdmissionFailureV1(
                        CapacityFailureCode.CONTEXT_LIMIT_INCONSISTENT
                    )
                max_output = min(
                    int(configured_max or stage_output_budget),
                    capability_record.max_output_tokens,
                )
                max_output_source = "route_capability_registry"
            elif capability_record is not None:
                route_context_limit = None
                route_context_source = None
                max_output = None
                max_output_source = None
            else:
                route_context_limit, route_context_source = (
                    _route_context_capability_v1(
                        model,
                        capability_record=None,
                        route_fingerprint=route_fingerprint,
                    )
                )
                max_output = int(configured_max or stage_output_budget)
                max_output_source = "offline_deterministic_gateway_manifest"
            if max_output is not None and max_output <= 0:
                raise ValueError("runtime stage output cap is unavailable")
            if route_selected and max_output is not None:
                if selected_route_output_caps[(role, lane)] > max_output:
                    raise CapacityAdmissionFailureV1(
                        CapacityFailureCode.OUTPUT_RESERVE_UNSATISFIED
                    )
                max_per_call = max(max_per_call, max_output)
            reasoning_reserve = (
                capability_record.reasoning_token_reserve
                if capability_record is not None else 0
            )
            if external_families and reasoning_reserve is None:
                if (
                    capability_record.reasoning_token_accounting
                    == "INCLUDED_IN_COMPLETION_CAP"
                    and capability_record.reasoning_output_reservation
                    == "WITHIN_COMPLETION_CAP"
                ):
                    reasoning_reserve = 0
                else:
                    raise CapacityAdmissionFailureV1(
                        CapacityFailureCode.ROUTE_CAPABILITY_UNKNOWN
                    )
            records.append({
                "role": role, "lane": lane,
                "provider_id_sha256": provider_id_sha256,
                "provider_name": str(provider.get("name") or ""),
                "provider_operator": operator,
                "model_id_sha256": model_id_sha256,
                "model_name": str(model.get("model_name") or ""),
                "protocol": str(provider["protocol"]),
                "route_fingerprint": route_fingerprint,
                "destination": destination,
                "max_output_tokens": max_output,
                "max_output_token_source": max_output_source,
                "route_context_capability_limit_tokens": (
                    route_context_limit
                ),
                "route_context_capability_source": route_context_source,
                "route_capability_sha256": (
                    _domain(external_families)
                    if external_families
                    else capability_record.capability_sha256
                    if capability_record is not None else None
                ),
                "route_capability_status": (
                    "VERIFIED_EXTERNAL_WORKLOAD_FAMILY_EVIDENCE"
                    if external_families
                    else capability_record.capability_status.value
                    if capability_record is not None
                    else "ISOLATED_OFFLINE_MANIFEST"
                ),
                **({
                    "external_workload_evidence_families": external_families,
                } if external_families else {}),
                "reasoning_token_accounting": (
                    capability_record.reasoning_token_accounting
                    if capability_record is not None
                    else "INCLUDED_IN_COMPLETION_CAP"
                ),
                "reasoning_output_reservation": (
                    capability_record.reasoning_output_reservation
                    if capability_record is not None
                    else "WITHIN_COMPLETION_CAP"
                ),
                "reasoning_token_reserve": (
                    reasoning_reserve
                ),
                "required_by_logical_stage_plan": route_selected,
            })
    records.sort(key=lambda item: (item["role"], item["lane"]))
    if used_external_evidence_sha256s != {
        item.evidence_sha256 for item in verified_external_workload_evidence
    }:
        raise CapacityAdmissionFailureV1(
            CapacityFailureCode.ROUTE_CAPABILITY_UNKNOWN
        )
    if not selected_routes <= {
        (str(item["role"]), str(item["lane"])) for item in records
    }:
        raise ValueError("required Full Short plan route is missing")
    runtime_fingerprint = collect_runtime_fingerprint_v2(
        db, project_id=project_id,
    )
    quality_reference_group = db.latest_quality_reference_group(
        project_id, profile_for_project(project),
    ) or {}
    selected_style = selected_style_reference_provenance(
        project, quality_reference_group,
        initialize_missing_profile=False,
    )
    if (
        selected_style.get("selection_status") == "selected"
        and selected_style.get("style_profile_state") == "missing"
        and project.metadata.get("style_sample_scope") == "draft_and_polish"
    ):
        raise ValueError("style profile must be initialized before authorization")
    public_style = {
        key: value for key, value in selected_style.items()
        if key != "style_profile_text"
    }

    scanner = SkillScanner([
        Path.home() / ".codex" / "skills",
        repo / ".agents" / "skills",
    ])
    available_skills = {
        item.name: item for item in scanner.scan([
            project_root / ".agents" / "skills",
        ])
    }
    full_short_stages = FULL_SHORT_BOUND_ROLES
    required_skill_names = sorted({
        name
        for stage in full_short_stages
        for name in (
            *REQUIRED_SKILLS.get(stage, []),
            *OPTIONAL_PROMPT_SKILLS.get(stage, []),
        )
    })
    missing_skills = [
        name for name in required_skill_names if name not in available_skills
    ]
    if missing_skills:
        raise ValueError("required Full Short Skill source is missing")
    skill_manifest = [{
        "name": name,
        "resolved_source_sha256": available_skills[name].resolved_source_sha256,
        "primary_document_sha256": available_skills[
            name
        ].primary_document_sha256,
        "executable": available_skills[name].executable,
        "approved": (
            db.is_skill_approved(
                name, available_skills[name].resolved_source_sha256,
            ) if available_skills[name].executable else True
        ),
    } for name in required_skill_names]
    if any(item["executable"] and not item["approved"] for item in skill_manifest):
        raise ValueError("required executable Skill is not approved")

    stage_skill_bytes = []
    skill_compactor = SkillPromptCompactor()
    for stage in full_short_stages:
        ordered_names = [
            *REQUIRED_SKILLS.get(stage, []),
            *OPTIONAL_PROMPT_SKILLS.get(stage, []),
        ]
        ordered_skills = [available_skills[name] for name in ordered_names]
        raw_prompt = "\n\n".join(item.instructions for item in ordered_skills)
        compacted_prompt = (
            skill_compactor.compact(raw_prompt, ordered_skills)
            if stage in {
                "planning", "draft", "polish", "review",
                "revision_plan", "final_review",
            }
            else raw_prompt
        )
        stage_skill_bytes.append({
            "stage": stage,
            "ordered_skill_names": ordered_names,
            "ordered_resolved_source_sha256": [
                item.resolved_source_sha256 for item in ordered_skills
            ],
            "current_baseline_prompt_utf8_sha256": hashlib.sha256(
                raw_prompt.encode("utf-8"),
            ).hexdigest(),
            "current_baseline_prompt_utf8_bytes": len(
                raw_prompt.encode("utf-8")
            ),
            "production_compacted_prompt_utf8_sha256": hashlib.sha256(
                compacted_prompt.encode("utf-8"),
            ).hexdigest(),
            "production_compacted_prompt_utf8_bytes": len(
                compacted_prompt.encode("utf-8")
            ),
        })

    workflow_source = inspect.getsource(WorkflowService._short_pipeline)
    cutover_truth = _workflow_cutover_source_truth()
    compactor_config = {
        "schema": "FullShortPromptCompactorConfigurationV1",
        "version": 1,
        "skill_prompt_compactor_source_sha256": _sha256(
            Path(inspect.getfile(SkillPromptCompactor)),
        ),
        "constraint_prompt_compactor_source_sha256": _sha256(
            Path(inspect.getfile(ConstraintPromptCompactor)),
        ),
        "skill_prompt_compactor_max_characters": skill_compactor.max_chars,
        "constraint_prompt_compactor_max_characters": (
            ConstraintPromptCompactor().max_chars
        ),
        "layered_context_stages": [
            "draft", "final_review", "planning", "polish", "review",
            "revision_plan",
        ],
    }
    production_path = {
        "entry": "WorkflowService.run_short->_short_pipeline",
        "workflow_short_pipeline_sha256": hashlib.sha256(
            workflow_source.encode("utf-8"),
        ).hexdigest(),
        "prompt_compactor_configuration": compactor_config,
        "current_baseline_skill_stage_bytes": stage_skill_bytes,
        "cutover_source_truth": cutover_truth,
        "resolved_skill_manifest": skill_manifest,
    }
    skill_v3_cutover = bool(cutover_truth["skill_v3_production_cutover"])
    planning_v2_cutover = bool(
        cutover_truth["planning_v2_production_cutover"]
    )
    if skill_v3_cutover or planning_v2_cutover:
        raise ValueError("retired production path unexpectedly reachable")
    workload = {
        "project_json_sha256": _sha256(project_root / "project.json"),
        "constraints_sha256": _sha256(project_root / "constraints.md"),
        "target_words": int(project_document["target_words"]),
    }
    short_canonical_snapshot = short_canonical_feature_snapshot(db, project_id)
    short_canonical_v2_enabled = bool(short_canonical_snapshot.enabled)
    if not short_canonical_v2_enabled:
        raise ValueError(
            "short canonical V2 READY authority requires exact project and environment flags"
        )
    runtime = {
        "story_state_revision": state.revision,
        "story_state_sha256": _domain(state.data),
        "maintenance_source_state_sha256": WorkflowService._text_hash(
            json.dumps(
                WorkflowService._short_maintenance_state_authority(state.data),
                ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            )
        ),
        "story_state_store_source_sha256": _sha256(
            Path(inspect.getfile(StoryStateStore)),
        ),
        "maintenance_projection_source_sha256": hashlib.sha256(
            inspect.getsource(
                WorkflowService._short_maintenance_state_authority,
            ).encode("utf-8"),
        ).hexdigest(),
        "story_state_source_truth": "sqlite.story_states.current_revision",
        "maintenance_source_truth": (
            "WorkflowService._short_maintenance_state_authority(StoryState)"
        ),
        "project_json_sha256": workload["project_json_sha256"],
        "runtime_fingerprint_policy_version": runtime_fingerprint.policy_version,
        "runtime_build_fingerprint_sha256": (
            runtime_fingerprint.build_fingerprint_sha256
        ),
        "runtime_execution_config_fingerprint_sha256": (
            runtime_fingerprint.execution_config_fingerprint_sha256
        ),
        "runtime_execution_fingerprint_sha256": (
            runtime_fingerprint.execution_fingerprint_sha256
        ),
        "runtime_build_definition_sha256": runtime_fingerprint.build[
            "definition_sha256"
        ],
        "runtime_execution_config_definition_sha256": (
            runtime_fingerprint.execution_config["definition_sha256"]
        ),
        "runtime_execution_definition_sha256": runtime_fingerprint.execution[
            "definition_sha256"
        ],
        "feature_flag_semantic_sha256": (
            runtime_fingerprint.feature_flag_semantic_sha256
        ),
        "feature_flag_provenance_sha256": (
            runtime_fingerprint.feature_flag_provenance_sha256
        ),
        "short_canonical_v2_enabled": short_canonical_v2_enabled,
        "short_canonical_v2_feature_snapshot_sha256": (
            short_canonical_snapshot.snapshot_hash
        ),
        "production_path_identity_sha256": _domain(production_path),
    }
    style = public_style
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
    route_manifest_sha256 = _domain(records)
    destination_manifest_sha256 = _domain(sorted(destinations))
    destination_operators = []
    for destination in sorted(destinations):
        operators = {
            str(record["provider_operator"])
            for record in records
            if record["destination"] == destination
        }
        if len(operators) != 1:
            raise FullShortExecutionBoundaryError(
                "DESTINATION_OPERATOR_IDENTITY_AMBIGUOUS"
            )
        destination_operators.append({
            "destination": destination,
            "operator_classification": next(iter(operators)),
        })
    selected_route_records = [
        item for item in records
        if item["required_by_logical_stage_plan"]
    ]
    authorization_eligible = bool(selected_route_records) and all(
        item["route_context_capability_source"] in {
            "route_capability_registry",
            "verified_external_workload_evidence",
        }
        and str(item["route_capability_status"]).startswith("VERIFIED_")
        for item in selected_route_records
    )
    actual = {
        "head": execution_head,
        "branch": _git(repo, "branch", "--show-current"),
        "run_id": run_id,
        "worktree_clean": _git(repo, "status", "--porcelain") == "",
        "project_id_sha256": hashlib.sha256(project_id.encode()).hexdigest(),
        "workload_sha256": _domain(workload),
        "runtime_authority_sha256": _domain(runtime),
        "style_reference_authority_sha256": _domain(style),
        "route_manifest_sha256": route_manifest_sha256,
        "route_capability_registry_sha256": (
            capability_registry.registry_sha256
            if capability_registry is not None else None
        ),
        "destination_manifest_sha256": destination_manifest_sha256,
        "egress_policy_sha256": _domain(egress),
        "response_capture_policy_sha256": RESPONSE_CAPTURE_POLICY_SHA256,
        "capture_attestation_scheme": "ED25519_CAPTURE_ANCHOR_V1",
        "capture_attestation_public_key": (
            attestation_store.capture_attestation_public_key
        ),
        "capture_attestation_public_key_sha256": (
            attestation_store.capture_attestation_public_key_sha256
        ),
        "logical_stage_plan_sha256": logical_stage_plan_sha256,
        "transport_recovery_policy_sha256": (
            TRANSPORT_RECOVERY_POLICY_SHA256
        ),
        "transport_recovery_policy_identity": "EXACT_REPLAY_ONLY",
        "logical_stage_recovery_policy_sha256": (
            LOGICAL_STAGE_RECOVERY_POLICY_SHA256
        ),
        "logical_stage_recovery_policy_identity": (
            "TWO_SLOT_MUTUALLY_EXCLUSIVE_TYPED_RECOVERY"
        ),
        "capacity_policy_registry_sha256": (
            DEFAULT_STAGE_CAPACITY_POLICY_REGISTRY_V1.identity_sha256
        ),
        "failure_architecture_identity": FAILURE_ARCHITECTURE_IDENTITY,
        "recovery_policy_registry_sha256": (
            FULL_SHORT_EXACT_RECOVERY_REGISTRY_SHA256
        ),
        "predispatch_state_machine_sha256": PREDISPATCH_STATE_MACHINE_SHA256,
        "nonce_reservation_policy_sha256": NONCE_RESERVATION_POLICY_SHA256,
        "observer_isolation_policy_sha256": OBSERVER_ISOLATION_POLICY_SHA256,
        "durable_failure_evidence_policy_sha256": (
            DURABLE_FAILURE_EVIDENCE_POLICY_SHA256
        ),
        "store_root_sha256": hashlib.sha256(
            str(exact_store_root).encode("utf-8"),
        ).hexdigest(),
        "skill_v3_production_cutover": skill_v3_cutover,
        "planning_v2_production_cutover": planning_v2_cutover,
        "external_action_counters": {
            "credential_lookup": 0, "provider_client_creation": 0,
            "provider_request": 0, "http_post": 0, "network": 0,
            "model": 0, "paid": 0,
        },
    }
    public = {
        "project_id": project_id,
        "run_id": run_id,
        "data_dir_sha256": hashlib.sha256(
            str(data_dir).encode("utf-8"),
        ).hexdigest(),
        "project_workload": workload,
        "runtime_authority": runtime,
        "style_reference_authority": style,
        "production_path_identity": production_path,
        "required_execution_roles": list(FULL_SHORT_REQUIRED_EXECUTION_ROLES),
        "authorization_eligible": authorization_eligible,
        "authorization_blocking_failure_id": (
            None if authorization_eligible
            else "capacity.route_capability_unknown"
        ),
        "routes": records,
        "route_capability_registry_sha256": (
            capability_registry.registry_sha256
            if capability_registry is not None else None
        ),
        "destinations": sorted(destinations),
        "destination_operators": destination_operators,
        "egress_policy": egress,
        "response_capture_policy": RESPONSE_CAPTURE_POLICY_V1,
        "capture_attestation_scheme": "ED25519_CAPTURE_ANCHOR_V1",
        "capture_attestation_public_key": (
            attestation_store.capture_attestation_public_key
        ),
        "capture_attestation_public_key_sha256": (
            attestation_store.capture_attestation_public_key_sha256
        ),
        "logical_stage_plan": logical_stage_plan,
        "logical_stage_plan_sha256": logical_stage_plan_sha256,
        "transport_recovery_policy": TRANSPORT_RECOVERY_POLICY_V1,
        "transport_recovery_policy_sha256": (
            TRANSPORT_RECOVERY_POLICY_SHA256
        ),
        "transport_recovery_policy_identity": "EXACT_REPLAY_ONLY",
        "logical_stage_recovery_policy": LOGICAL_STAGE_RECOVERY_POLICY_V1,
        "logical_stage_recovery_policy_sha256": (
            LOGICAL_STAGE_RECOVERY_POLICY_SHA256
        ),
        "logical_stage_recovery_policy_identity": (
            "TWO_SLOT_MUTUALLY_EXCLUSIVE_TYPED_RECOVERY"
        ),
        "capacity_policy_registry_sha256": (
            DEFAULT_STAGE_CAPACITY_POLICY_REGISTRY_V1.identity_sha256
        ),
        "failure_architecture_identity": FAILURE_ARCHITECTURE_IDENTITY,
        "recovery_policy_registry": FULL_SHORT_EXACT_RECOVERY_REGISTRY_V1,
        "recovery_policy_registry_sha256": (
            FULL_SHORT_EXACT_RECOVERY_REGISTRY_SHA256
        ),
        "predispatch_state_machine": PREDISPATCH_STATE_MACHINE_V1,
        "predispatch_state_machine_sha256": PREDISPATCH_STATE_MACHINE_SHA256,
        "nonce_reservation_policy": NONCE_RESERVATION_POLICY_V1,
        "nonce_reservation_policy_sha256": NONCE_RESERVATION_POLICY_SHA256,
        "observer_isolation_policy": OBSERVER_ISOLATION_POLICY_V1,
        "observer_isolation_policy_sha256": OBSERVER_ISOLATION_POLICY_SHA256,
        "durable_failure_evidence_policy": DURABLE_FAILURE_EVIDENCE_POLICY_V1,
        "durable_failure_evidence_policy_sha256": (
            DURABLE_FAILURE_EVIDENCE_POLICY_SHA256
        ),
        "maximum_configured_output_tokens_per_call": max_per_call,
        "store_root": str(exact_store_root),
        "store_root_sha256": hashlib.sha256(
            str(exact_store_root).encode("utf-8"),
        ).hexdigest(),
    }
    return actual, public


def preflight_full_short_control_plane(
    args: argparse.Namespace, raw: bytes, *, external_actions_enabled: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Rebuild every live binding before any credential or client exists."""

    parsed = json.loads(raw.decode("utf-8"))
    policy = parsed["policy"]
    bindings = parsed["public_bindings"]
    authorization = validate_full_short_canonical_authorization_v1(
        raw, policy=policy, public_bindings=bindings,
    )
    if policy.get("monetary_cost_cap_state") != "UNKNOWN_NOT_SEALED":
        raise FullShortExecutionBoundaryError(
            "FULL_SHORT_MONETARY_COST_STATE_NOT_EXACT"
        )
    actual, live_public = collect_live_bindings(
        repo=args.repo, data_dir=args.data_dir,
        project_id=str(bindings["project_id"]),
        run_id=str(policy["run_id"]),
        logical_stage_plan=list(bindings["logical_stage_plan"]),
        store_root=args.store_root,
        verified_external_workload_evidence=getattr(
            args, "verified_external_workload_evidence", (),
        ),
        external_workload_authorized_cases=getattr(
            args, "external_workload_authorized_cases", (),
        ),
        external_workload_authorization_sha256=getattr(
            args, "external_workload_authorization_sha256", None,
        ),
        external_workload_verification_keys=getattr(
            args, "external_workload_verification_keys", None,
        ),
    )
    if external_actions_enabled and not live_public.get(
        "authorization_eligible"
    ):
        raise CapacityAdmissionFailureV1(
            CapacityFailureCode.ROUTE_CAPABILITY_UNKNOWN,
        )
    if live_public != bindings:
        raise FullShortExecutionBoundaryError("PUBLIC_BINDINGS_DRIFT")
    preflight = validate_full_short_preflight_v1(
        policy=policy, actual=actual,
        authorization_text_sha256=authorization["authorization_text_sha256"],
        external_actions_enabled=external_actions_enabled,
    )
    return authorization, preflight


def _authorization_raw(args: argparse.Namespace) -> bytes:
    supplied = getattr(args, "authorization_raw", None)
    if isinstance(supplied, bytes):
        return supplied
    return Path(args.authorization).read_bytes()


def _completion_elapsed_recheck(policy: dict, ledger: dict) -> int:
    """Fail closed if the elapsed cap expired after the last dispatch."""

    try:
        created_at = datetime.fromisoformat(
            str(ledger["created_at"]).replace("Z", "+00:00"),
        )
    except (KeyError, ValueError) as exc:
        raise FullShortExecutionBoundaryError(
            "FULL_SHORT_LEDGER_CREATED_AT_INVALID"
        ) from exc
    elapsed = max(
        0,
        int((datetime.now(timezone.utc) - created_at).total_seconds()),
    )
    if elapsed > int(policy["maximum_elapsed_seconds"]):
        raise FullShortExecutionBoundaryError(
            "FULL_SHORT_MAXIMUM_ELAPSED_EXPIRED_AT_COMPLETION"
        )
    return elapsed


def _registry_from_factory(
    factory: Callable[..., ProviderRegistry] | None,
    *, db: Database, secret_store: Any,
    observer: FullShortDispatchLedgerObserverV1,
    http_transport_factory: Callable[..., Any] | None,
) -> ProviderRegistry:
    kwargs: dict[str, Any] = {
        "transport_policy": SingleDispatchTransportPolicyV1.phase_b(),
        "attempt_observer": observer,
    }
    if factory is None:
        if http_transport_factory is not None:
            raise ValueError(
                "an HTTP transport factory requires a lowest-seam registry factory"
            )
        return ProviderRegistry(db, secret_store, **kwargs)
    signature = inspect.signature(factory)
    accepts_http_transport = (
        "http_transport_factory" in signature.parameters
        or any(
            item.kind is inspect.Parameter.VAR_KEYWORD
            for item in signature.parameters.values()
        )
    )
    if http_transport_factory is not None and not accepts_http_transport:
        raise FullShortExecutionBoundaryError(
            "OFFLINE_REGISTRY_CANNOT_BIND_HTTP_TRANSPORT"
        )
    if accepts_http_transport:
        kwargs["http_transport_factory"] = http_transport_factory
    registry = factory(db, secret_store, **kwargs)
    if http_transport_factory is not None and (
        getattr(registry, "transport_factory", None)
        is not http_transport_factory
    ):
        raise FullShortExecutionBoundaryError(
            "OFFLINE_REGISTRY_TRANSPORT_BINDING_NOT_EXACT"
        )
    return registry


async def _launch_exact_short(
    manager: RunTaskManager, *, execution_id: str, project_id: str,
    operation: Callable[[str], Any], terminal_finalizer: Callable[..., Any] | None = None,
    already_reserved: bool = False,
) -> None:
    """Use the reservation API when present, retaining baseline compatibility."""

    reserve = getattr(manager, "reserve_exact_once", None)
    launch = getattr(manager, "launch_reserved_exact_once", None)
    if callable(reserve) and callable(launch):
        if not already_reserved:
            reserve(execution_id, project_id, "short-story")
        launch(
            execution_id, operation, terminal_finalizer=terminal_finalizer,
        )
    else:
        if already_reserved:
            raise FullShortExecutionBoundaryError(
                "FULL_SHORT_EXACT_RESERVATION_API_UNAVAILABLE"
            )
        manager.start_exact_once(
            execution_id, project_id, "short-story", operation,
            terminal_finalizer=terminal_finalizer,
        )
    task = manager.tasks.get(execution_id)
    if task is None:
        raise FullShortExecutionBoundaryError(
            "FULL_SHORT_RESERVED_TASK_NOT_LAUNCHED"
        )
    await task


def _full_short_runtime_components(
    *, repo: Path, data_dir: Path, project_id: str, execution_id: str,
    registry: ProviderRegistry, manager: RunTaskManager | None = None,
) -> tuple[Database, Any, WorkflowService, RunTaskManager]:
    """Build the exact production task-manager and WorkflowService assembly."""

    settings = Settings(data_dir.resolve(strict=True))
    configure_runtime_environment(settings.data_dir)
    db = Database(settings.database_path)
    db.migrate()
    projects = ProjectStore(db, settings.data_dir / "projects")
    project = projects.get(project_id)
    references = ReferenceLibrary(db, settings.data_dir / "references")
    local_nlp = LocalNLPManager(settings.data_dir / "local-nlp.json")
    skills = SkillGate(db, SkillScanner([
        Path.home() / ".codex" / "skills",
        repo / ".agents" / "skills",
    ]))
    service = WorkflowService(
        db, projects, ModelGateway(db, registry), skills,
        settings.data_dir / "crewai", local_nlp=local_nlp,
        references=references,
        hybrid_skill_context_shadow_enabled=False,
    )
    manager = manager or RunTaskManager(db)
    return db, project, service, manager


async def run_full_short_workflow_path(
    *, repo: Path, data_dir: Path, project_id: str, execution_id: str,
    registry: ProviderRegistry,
) -> tuple[Database, Any, dict[str, Any]]:
    """Run the exact production task-manager and WorkflowService assembly."""

    db, project, service, manager = _full_short_runtime_components(
        repo=repo, data_dir=data_dir, project_id=project_id,
        execution_id=execution_id, registry=registry,
    )
    await _launch_exact_short(
        manager, execution_id=execution_id, project_id=project.id,
        operation=lambda run_id: service.run_short(
            project.id, run_id=run_id, use_crewai=True,
        ),
    )
    return db, project, db.get_run(execution_id) or {}


class _OfflineExecutionCapabilityV1:
    """Unforgeable-by-marker authority used only by repository dry runs."""

    __slots__ = ()


_OFFLINE_EXECUTION_CAPABILITY_V1 = _OfflineExecutionCapabilityV1()


async def execute_full_short_control_plane(
    args: argparse.Namespace,
    authorization: dict[str, Any],
    *,
    external_actions_enabled: bool,
    secret_store_factory: Callable[[], Any],
    registry_factory: Callable[..., ProviderRegistry] | None = None,
    http_transport_factory: Callable[..., Any] | None = None,
    required_stage_roles: tuple[str, ...] = (),
    outer_campaign_usage_guard: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Enter the production boundary; disabled actions are not executable here."""

    if not external_actions_enabled:
        raise FullShortExecutionBoundaryError(
            "DISABLED_EXTERNAL_ACTIONS_REQUIRE_EXPLICIT_OFFLINE_SEAMS"
        )
    return await _execute_full_short_control_plane_with_capability(
        args, authorization, external_actions_enabled=True,
        secret_store_factory=secret_store_factory,
        registry_factory=registry_factory,
        http_transport_factory=http_transport_factory,
        required_stage_roles=required_stage_roles,
        outer_campaign_usage_guard=outer_campaign_usage_guard,
        offline_capability=None,
    )


async def _execute_full_short_control_plane_offline(
    args: argparse.Namespace,
    authorization: dict[str, Any],
    *,
    secret_store: MemorySecretStore,
    http_transport_factory: Callable[..., Any],
    required_stage_roles: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Narrow private entry for deterministic, lowest-seam offline rehearsals."""

    if type(secret_store) is not MemorySecretStore or http_transport_factory is None:
        raise FullShortExecutionBoundaryError(
            "DISABLED_EXTERNAL_ACTIONS_REQUIRE_EXPLICIT_OFFLINE_SEAMS"
        )
    # The only offline registry is repository-owned and replaces every real
    # adapter client at the lowest HTTP seam.  Callers cannot substitute an
    # arbitrary factory that performs credential or network work in its
    # constructor.
    from tools.canary.first_trustworthy_full_short_dry_run import (
        _LowestHttpSeamRegistry,
    )
    return await _execute_full_short_control_plane_with_capability(
        args, authorization, external_actions_enabled=False,
        secret_store_factory=lambda: secret_store,
        registry_factory=_LowestHttpSeamRegistry,
        http_transport_factory=http_transport_factory,
        required_stage_roles=required_stage_roles,
        outer_campaign_usage_guard=None,
        offline_capability=_OFFLINE_EXECUTION_CAPABILITY_V1,
    )


async def _execute_full_short_control_plane_with_capability(
    args: argparse.Namespace,
    authorization: dict[str, Any],
    *,
    external_actions_enabled: bool,
    secret_store_factory: Callable[[], Any],
    registry_factory: Callable[..., ProviderRegistry] | None = None,
    http_transport_factory: Callable[..., Any] | None = None,
    required_stage_roles: tuple[str, ...] = (),
    outer_campaign_usage_guard: Mapping[str, Any] | None,
    offline_capability: _OfflineExecutionCapabilityV1 | None,
) -> dict[str, Any]:
    """Execute the real control-plane, task manager, and WorkflowService path.

    Production supplies no factories and therefore uses the keyring plus the
    real provider transport.  An offline replay may replace only the secret
    store and the registry's lowest HTTP transport.
    """

    if external_actions_enabled:
        if offline_capability is not None:
            raise FullShortExecutionBoundaryError(
                "OFFLINE_CAPABILITY_FOR_LIVE_EXECUTION_FORBIDDEN"
            )
    elif offline_capability is not _OFFLINE_EXECUTION_CAPABILITY_V1:
        raise FullShortExecutionBoundaryError(
            "DISABLED_EXTERNAL_ACTIONS_REQUIRE_EXPLICIT_OFFLINE_SEAMS"
        )

    try:
        raw = _authorization_raw(args)
        raw_sha256 = hashlib.sha256(raw).hexdigest()
        if raw_sha256 != args.activated_sha256:
            raise FullShortExecutionBoundaryError(
                "ACTIVATED_AUTHORIZATION_SHA256_MISMATCH"
            )
        live_authorization, _preflight = preflight_full_short_control_plane(
            args, raw, external_actions_enabled=external_actions_enabled,
        )
        if live_authorization != authorization:
            raise FullShortExecutionBoundaryError(
                "FULL_SHORT_AUTHORIZATION_OBJECT_DRIFT"
            )
    except Exception as exc:
        _persist_preflight_failure(
            args, exc, boundary="full_short.execution_preflight",
        )
        raise
    policy = authorization["policy"]
    bindings = authorization["public_bindings"]
    verified_external_evidence = tuple(
        getattr(args, "verified_external_workload_evidence", ())
    )
    external_workload_capacity_issuer = (
        _issue_verified_external_workload_capacity_issuer_v1(
            evidence_sha256s=(
                item.evidence_sha256 for item in verified_external_evidence
            ),
        )
        if verified_external_evidence else None
    )

    def recheck_live_authority() -> None:
        """Re-collect every credential-free binding at each dispatch edge."""

        current, _receipt = preflight_full_short_control_plane(
            args, raw, external_actions_enabled=external_actions_enabled,
        )
        if current != authorization:
            raise FullShortExecutionBoundaryError(
                "FULL_SHORT_AUTHORIZATION_OBJECT_DRIFT"
            )

    settings = Settings(args.data_dir.resolve(strict=True))
    configure_runtime_environment(settings.data_dir)
    db = Database(settings.database_path)
    db.migrate()
    execution_id = policy["run_id"]
    manager = RunTaskManager(db)
    runtime_journal_path = (
        args.store_root / f"{execution_id}.runtime-journal-v1.json"
    )
    if runtime_journal_path.exists():
        reconciliation = FullShortRestartReconcilerV1().reconcile(
            runtime_journal_path
        )
        failure = FullShortExecutionBoundaryError(
            "AMBIGUOUS_OR_UNCLOSED_DISPATCH_NO_RESTART"
        )
        failure.add_note(
            "RUNTIME_RECONCILIATION_DECISION="
            + reconciliation.decision.value
        )
        failure.add_note(
            "RUNTIME_RECONCILIATION_HEAD_SHA256="
            + reconciliation.journal_head_sha256
        )
        raise failure
    if db.get_run(execution_id) is not None:
        if manager.fail_closed_exact_once_reservation(
            execution_id,
            reason_code="ORPHANED_EXACT_ONCE_RESERVATION_NO_RESUME",
        ):
            failure = FullShortExecutionBoundaryError(
                "FULL_SHORT_ORPHANED_RESERVATION_FAILED_CLOSED"
            )
            failure.add_note("NEW_SINGLE_USE_AUTHORIZATION_REQUIRED")
            raise failure
    manager.reserve_exact_once(
        execution_id, str(bindings["project_id"]), "short-story",
    )
    prelaunch_state = {"approval_created": False}

    def prelaunch(step: Callable[[], Any], boundary: str) -> Any:
        try:
            return step()
        except Exception as exc:
            _terminalize_prelaunch_failure(
                args, exc, boundary=boundary, manager=manager,
                execution_id=execution_id,
                approval_created=prelaunch_state["approval_created"],
            )
            raise

    prelaunch(
        recheck_live_authority,
        "full_short.prelaunch.live_authority_recheck",
    )
    store = prelaunch(
        lambda: FullShortDurableExecutionStoreV1(
            repo_root=args.repo, store_root=args.store_root,
        ),
        "full_short.prelaunch.store_binding",
    )
    permission = prelaunch(
        lambda: store.create_permission(
            execution_id=execution_id,
            authorization_text_sha256=args.activated_sha256,
            policy=policy, external_actions_enabled=external_actions_enabled,
        ),
        "full_short.prelaunch.permission",
    )
    approval = prelaunch(
        lambda: store.create_jit_approval(
            execution_id=execution_id, policy=policy, permission=permission,
            external_actions_enabled=external_actions_enabled,
        ),
        "full_short.prelaunch.approval",
    )
    prelaunch_state["approval_created"] = True
    runtime_journal = prelaunch(
        lambda: DurableExecutionJournalV1.create(
            runtime_journal_path,
            execution_id=execution_id,
            initial_state=ExecutionState.TEMPLATE_READY,
        ),
        "full_short.prelaunch.runtime_journal",
    )
    runtime_journal.transition(
        ExecutionState.AUTHORIZED,
        transition_id="canonical-authorization-activated",
        boundary_id="FS.CONTROL.PREFLIGHT",
    )
    runtime_journal.transition(
        ExecutionState.APPROVED,
        transition_id="jit-approval-created",
        boundary_id="FS.CONTROL.PREFLIGHT",
    )
    runtime_kernel = FullShortExecutionKernel(
        registry=DEFAULT_FAILURE_BOUNDARY_REGISTRY_V1,
        journal=runtime_journal,
    )

    def prepare_predispatch_with_kernel() -> dict[str, Any]:
        with activate_full_short_kernel_v1(runtime_kernel):
            return store.prepare_predispatch_ledger(
                execution_id=execution_id, policy=policy,
                permission=permission, approval=approval,
                external_actions_enabled=external_actions_enabled,
            )

    prelaunch(
        prepare_predispatch_with_kernel,
        "full_short.prelaunch.predispatch_ledger",
    )
    observer = prelaunch(
        lambda: FullShortDispatchLedgerObserverV1(
            store=store, execution_id=execution_id, policy=policy,
            authorized_routes=tuple(bindings["routes"]),
            egress_policy=bindings["egress_policy"],
            external_actions_enabled=external_actions_enabled,
            live_authority_recheck=recheck_live_authority,
            outer_campaign_usage_guard=outer_campaign_usage_guard,
            external_workload_capacity_issuer=(
                external_workload_capacity_issuer
            ),
        ),
        "full_short.prelaunch.observer",
    )
    registry = prelaunch(
        lambda: _registry_from_factory(
            registry_factory, db=db, secret_store=secret_store_factory(),
            observer=observer, http_transport_factory=http_transport_factory,
        ),
        "full_short.prelaunch.registry",
    )
    db, project, service, manager = prelaunch(
        lambda: _full_short_runtime_components(
            repo=args.repo, data_dir=settings.data_dir,
            project_id=str(bindings["project_id"]), execution_id=execution_id,
            registry=registry, manager=manager,
        ),
        "full_short.prelaunch.runtime_components",
    )
    closure_state: dict[str, Any] = {}

    def terminal_closure(
        actual_run_id: str, _operation_result: object,
        live_authority: dict[str, object],
    ) -> Callable[[], dict[str, Any]]:
        if actual_run_id != execution_id:
            raise FullShortExecutionBoundaryError(
                "FULL_SHORT_TERMINAL_RUN_ID_DRIFT"
            )
        ledger = store.load_ledger(execution_id)
        completed_stage_receipts = ledger.get("completed_stage_receipts")
        if not isinstance(completed_stage_receipts, list):
            raise FullShortExecutionBoundaryError(
                "FULL_SHORT_STAGE_RECEIPTS_NOT_AVAILABLE"
            )
        observed_roles = tuple(
            str(item.get("role") or "")
            for item in completed_stage_receipts
            if isinstance(item, dict)
        )
        required_roles = tuple(
            required_stage_roles or policy.get("required_stage_roles") or ()
        )
        closure_state["observed_roles"] = list(observed_roles)
        if sorted(set(required_roles) - set(observed_roles)):
            raise FullShortExecutionBoundaryError(
                "FULL_SHORT_REQUIRED_STAGE_ROLE_NOT_EXECUTED"
            )
        run_root = Path(str(live_authority["run_root"]))
        project_root = Path(str(live_authority["project_root"]))
        terminal = runtime_kernel.execute_boundary_sync(
            "FS.TERMINAL.VERIFY_COMMIT",
            lambda: verify_short_completion_v1(
                project_root=project_root, run_root=run_root,
                run_identity=execution_id,
                workload_sha256=policy["workload_sha256"],
                workflow_final_status="completed",
                live_parity_status="exact",
                live_story_state_revision=int(
                    live_authority["story_state_revision"]
                ),
                live_story_state_sha256=str(
                    live_authority["story_state_sha256"]
                ),
                live_story_state_data=dict(
                    live_authority["story_state_data"]
                ),
                expected_base_story_state_revision=int(
                    bindings["runtime_authority"]["story_state_revision"]
                ),
                expected_base_story_state_sha256=str(
                    bindings["runtime_authority"]["story_state_sha256"]
                ),
                expected_maintenance_source_state_sha256=str(
                    bindings["runtime_authority"]
                    ["maintenance_source_state_sha256"]
                ),
                short_canonical_v2_enabled=True,
                workflow_service=service, project=project,
            ),
        )
        closure_state["terminal"] = terminal
        if terminal.get("completion_goal_outcome") != COMPLETION_GOAL:
            raise FullShortExecutionBoundaryError(
                "FULL_SHORT_TERMINAL_VERIFICATION_NOT_EXACT"
            )
        try:
            elapsed_seconds = _completion_elapsed_recheck(policy, ledger)
            capacity_admission_receipts = store.verify_completion_capacity_receipts(
                execution_id=execution_id, policy=policy, ledger=ledger,
            )
            nonce = store.load_nonce(execution_id)
            receipt = build_full_short_completion_receipt_v1(
                execution_id=execution_id, policy=policy,
                durable_store=store,
                permission_sha256=permission["permission_sha256"],
                signed_approval_sha256=approval["signed_approval_sha256"],
                nonce_sha256=nonce["nonce_sha256"], ledger=ledger,
                final_bindings={
                    # Terminal verification binds the canonical UTF-8 text
                    # identity used by Final Review.  Physical file bytes are
                    # independently exact-bound by the mutation journal.
                    "manuscript_sha256": str(
                        terminal["final_manuscript_sha256"]
                    ),
                    "chapter_sha256": _sha256(
                        project_root / "chapters" / "chapter-01.md"
                    ),
                    "canon_sha256": str(live_authority["canon_sha256"]),
                    "story_state_sha256": str(
                        live_authority["story_state_sha256"]
                    ),
                    "quality_checkpoint_sha256": _sha256(
                        run_root / "outputs" / "quality-checkpoint.json"
                    ),
                    "terminal_verification_sha256": str(
                        terminal["verification_receipt_sha256"]
                    ),
                },
                terminal_verification=terminal,
                capacity_admission_receipts=capacity_admission_receipts,
            )
        except Exception as exc:
            closure_state["terminal_failure"] = _safe_failure_metadata(
                exc, boundary="full_short.terminal_receipt",
            )
            raise
        closure_state.update({
            "terminal": terminal, "ledger": ledger,
            "elapsed_seconds": elapsed_seconds,
            "observed_roles": list(observed_roles),
            "receipt": receipt,
        })

        def commit_after_saga_cleanup() -> dict[str, Any]:
            try:
                completion = runtime_kernel.execute_boundary_sync(
                    "FS.TERMINAL.VERIFY_COMMIT",
                    lambda: store.commit_completion(
                        execution_id=execution_id,
                        policy=policy,
                        receipt=receipt,
                    ),
                )
            except Exception as exc:
                closure_state["terminal_failure"] = _safe_failure_metadata(
                    exc, boundary="full_short.completion_commit",
                )
                raise
            closure_state["completion"] = completion
            return completion

        return commit_after_saga_cleanup

    terminal_finalizer = prelaunch(
        lambda: service.bind_full_short_terminal_finalizer(
            execution_id, project.id, terminal_closure,
        ),
        "full_short.prelaunch.terminal_finalizer",
    )

    async def supervised_operation(actual_run_id: str) -> object:
        try:
            with activate_full_short_kernel_v1(runtime_kernel):
                return await service.run_short(
                    project.id, run_id=actual_run_id, use_crewai=True,
                )
        except Exception as exc:
            # The task supervisor persists only safe failure evidence and
            # deliberately absorbs workflow exceptions into terminal state.
            # Retain the live object in memory so the exact runner's summary
            # cannot destroy its child provenance.
            closure_state["workflow_exception"] = exc
            closure_state["workflow_failure"] = _safe_failure_metadata(
                exc, boundary="full_short.workflow_operation",
            )
            raise

    try:
        await _launch_exact_short(
            manager, execution_id=execution_id, project_id=project.id,
            operation=supervised_operation,
            terminal_finalizer=terminal_finalizer,
            already_reserved=True,
        )
    except Exception:
        run = db.get_run(execution_id)
        if run is not None and run.get("status") == "queued":
            if not manager.fail_closed_exact_once_reservation(
                execution_id,
                reason_code="FULL_SHORT_LAUNCH_FAILED_BEFORE_RUNNING",
            ):
                raise FullShortExecutionBoundaryError(
                    "FULL_SHORT_PRELAUNCH_RESERVATION_CLEANUP_FAILED"
                )
        raise
    finally:
        close = getattr(registry, "close", None)
        if callable(close):
            try:
                closed = close()
                if inspect.isawaitable(closed):
                    await closed
            except Exception as close_error:
                # Resource-close diagnostics are secondary evidence.  They
                # must never replace the workflow/terminal outcome selected
                # above or trigger a new provider attempt.
                closure_state["registry_close_failure"] = {
                    "exception_type": type(close_error).__name__,
                    "failure_sha256": hashlib.sha256(
                        type(close_error).__name__.encode("utf-8")
                    ).hexdigest(),
                }
    result = db.get_run(execution_id) or {}
    if result.get("status") != "completed":
        terminal = closure_state.get("terminal")
        diagnostic = {
            "status": result.get("status"),
            "current_stage": result.get("current_stage"),
            "safe_error": result.get("error"),
            "observed_roles": closure_state.get("observed_roles"),
            "terminal_outcome": (
                terminal.get("completion_goal_outcome")
                if isinstance(terminal, dict) else None
            ),
            "final_artifact_binding": (
                terminal.get("final_artifact", {}).get("binding_status")
                if isinstance(terminal, dict) else None
            ),
            "ready_authority_binding": (
                terminal.get("final_artifact", {}).get(
                    "ready_authority_binding_status"
                ) if isinstance(terminal, dict) else None
            ),
            "checkpoint_binding": (
                terminal.get("final_checkpoint", {}).get("binding_status")
                if isinstance(terminal, dict) else None
            ),
            "terminal_failure": closure_state.get("terminal_failure"),
            "workflow_failure": closure_state.get("workflow_failure"),
        }
        failure = _supervised_run_not_completed_failure(
            diagnostic,
            closure_state.get("workflow_exception"),
        )
        raise failure
    completion = closure_state.get("completion")
    if not isinstance(completion, dict):
        raise FullShortExecutionBoundaryError(
            "FULL_SHORT_COMPLETION_NOT_COMMITTED_AFTER_SAGA_CLEANUP"
        )
    return {
        "completion": completion,
        "terminal": closure_state["terminal"],
        "workflow_result": result,
        "ledger": closure_state["ledger"],
        "elapsed_seconds_at_completion_recheck": closure_state[
            "elapsed_seconds"
        ],
        "observed_roles": closure_state["observed_roles"],
        "call_plan": list(getattr(registry, "call_plan", ())),
        "verified_actual_usage": completion.get("verified_actual_usage"),
    }


async def _execute(args: argparse.Namespace, authorization: dict) -> dict:
    """Backward-compatible production entry used by focused tests/tools."""

    result = await execute_full_short_control_plane(
        args, authorization, external_actions_enabled=True,
        secret_store_factory=KeyringSecretStore,
    )
    return result["completion"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--store-root", type=Path, required=True)
    parser.add_argument("--activated-sha256", required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    args.repo = args.repo.resolve(strict=True)
    try:
        raw = args.authorization.read_bytes()
        actual_sha256 = hashlib.sha256(raw).hexdigest()
        if actual_sha256 != args.activated_sha256:
            raise FullShortExecutionBoundaryError(
                "ACTIVATED_AUTHORIZATION_SHA256_MISMATCH"
            )
        authorization, preflight = preflight_full_short_control_plane(
            args, raw,
            external_actions_enabled=args.execute,
        )
    except Exception as exc:
        receipt = _persist_preflight_failure(args, exc)
        raise SystemExit(
            "FULL_SHORT_PREFLIGHT_FAILED:"
            + receipt["failure_graph_sha256"]
        ) from exc
    if not args.execute:
        print(json.dumps({
            "status": "exact", "preflight_receipt_sha256": preflight[
                "preflight_receipt_sha256"
            ],
            "authorization_text_sha256": actual_sha256,
            "credential_lookup_count": 0,
            "real_provider_request_attempts": 0,
            "network_calls": 0, "model_calls": 0, "paid_calls": 0,
        }, sort_keys=True))
        return 0
    completion = asyncio.run(_execute(args, authorization))
    print(json.dumps({
        "status": "completed",
        "completion_receipt_sha256": completion["completion_receipt_sha256"],
        "provider_request_count": completion["provider_request_count"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
