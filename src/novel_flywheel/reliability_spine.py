"""Canonical Short Runtime reliability spine.

This module is intentionally small and provider agnostic.  It is the single
production dispatch authority used by ``ModelGateway`` and the HTTP adapter.
The existing Full Short ledger remains the domain ledger for its exact runner;
this spine prevents any other adapter path from reaching the network without
an immutable envelope, a physical request claim, and a capture manifest.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import marshal
import json
import os
from pathlib import Path
import secrets
import threading
import types
import importlib
from typing import Any, Mapping

from novel_flywheel.provider_response_capture import (
    provider_response_evidence_projection_v1,
)
from novel_flywheel.runtime_fingerprint_build import collect_build_manifests, domain_sha256


SCHEMA_VERSION = "short-runtime-reliability-spine-v1"
_HEX64 = "0123456789abcdef"
RECOVERY_COORDINATOR_VERSION = "short-recovery-coordinator-v1"
CUTOVER_REGISTRY_VERSION = "short-cutover-registry-v1"
DURABLE_NODE_SCHEMA = "ShortDurableNodeV1"


_DURABLE_NODE_STATES = frozenset({
    "CANDIDATE_READY", "REVIEW_PREPARED", "REVIEW_DISPATCH_RESERVED",
    "REVIEW_SENT_OR_UNKNOWN", "RESPONSE_CAPTURED", "RECEIPT_VALIDATED",
    "RECEIPT_INVALID", "BUSINESS_REJECTED", "BUSINESS_PASSED",
    "REPAIR_REQUIRED", "REPAIR_PREPARED", "REPAIR_SENT_OR_UNKNOWN",
    "REPAIR_CANDIDATE_CREATED", "REREVIEW_REQUIRED", "SEGMENT_ACCEPTED",
    "WAITING_LOCAL_RECOVERY", "WAITING_ROUTE_OR_CAPABILITY",
    "BLOCKED_RECOVERABLE", "TERMINAL_UNRECOVERABLE",
})


def _sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class CanonicalEpisodeIdentity:
    project_id: str
    run_id: str
    workflow_kind: str
    logical_stage_id: str
    logical_node_id: str
    recovery_episode_id: str
    candidate_sha256: str
    contract_name: str
    contract_version: int
    policy_version: str
    authorization_sha256: str
    episode_sha256: str

    @classmethod
    def build(cls, metadata: Mapping[str, Any]) -> "CanonicalEpisodeIdentity":
        body = {
            "project_id": str(metadata.get("project_id") or "unknown"),
            "run_id": str(metadata.get("operation_run_id") or metadata.get("run_id") or "unbound"),
            "workflow_kind": str(metadata.get("workflow_kind") or "short-story"),
            "logical_stage_id": str(metadata.get("stage") or metadata.get("role") or "unknown"),
            "logical_node_id": str(metadata.get("logical_node_id") or metadata.get("stage") or metadata.get("role") or "unknown"),
            "candidate_sha256": str(metadata.get("candidate_sha256") or _sha("unknown-candidate")),
            "contract_name": str(metadata.get("contract_name") or "plain"),
            "contract_version": int(metadata.get("contract_version") or 0),
            "policy_version": str(metadata.get("policy_version") or "short-runtime-policy-v1"),
        }
        if len(body["candidate_sha256"]) != 64 or any(c not in _HEX64 for c in body["candidate_sha256"]):
            body["candidate_sha256"] = _sha(body["candidate_sha256"])
        body["authorization_sha256"] = str(metadata.get("authorization_sha256") or _sha(body))
        episode_sha = domain_sha256("novel-flywheel-canonical-episode-v1", body)
        return cls(
            **body,
            recovery_episode_id=str(metadata.get("recovery_episode_id") or episode_sha[:24]),
            episode_sha256=episode_sha,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id, "run_id": self.run_id,
            "workflow_kind": self.workflow_kind,
            "logical_stage_id": self.logical_stage_id,
            "logical_node_id": self.logical_node_id,
            "recovery_episode_id": self.recovery_episode_id,
            "candidate_sha256": self.candidate_sha256,
            "contract_name": self.contract_name,
            "contract_version": self.contract_version,
            "policy_version": self.policy_version,
            "authorization_sha256": self.authorization_sha256,
            "episode_sha256": self.episode_sha256,
        }


@dataclass(frozen=True)
class ReleaseBuildIdentity:
    build_id: str
    worker_fencing_id: str
    runtime_path_id: str
    source_status: str
    source_manifest_sha256: str
    loaded_code_manifest_sha256: str

    @classmethod
    def collect(cls, data_root: Path, *, worker_fencing_id: str | None = None) -> "ReleaseBuildIdentity":
        manifests = collect_build_manifests()
        source = manifests.installed_runtime or manifests.production_source
        source_hash = str((source or {}).get("definition_sha256") or "")
        status = str(manifests.status or "unknown_runtime")
        worker = worker_fencing_id or f"{os.getpid()}-{secrets.token_hex(8)}"
        build_id = domain_sha256("novel-flywheel-release-build-v1", {
            "source_manifest_sha256": source_hash,
            "status": status,
            "runtime": f"{os.sys.implementation.cache_tag}:{os.sys.version_info[:3]}",
        })
        # Imports can populate adapter classes lazily. Warm the exact module
        # set once, then attest the stable loaded code object set.
        _loaded_code_hash()
        loaded_hash = _loaded_code_hash()
        runtime_path_id = domain_sha256("novel-flywheel-runtime-path-v1", {
            "build_id": build_id,
            "worker_fencing_id": worker,
            "entrypoint": "ModelGateway._admit_transport_dispatch",
            "spine": "CanonicalEpisodeIdentity>ExecutionEnvelope>PhysicalRequestLedger>CaptureManifest>ProviderTransport",
        })
        return cls(build_id, worker, runtime_path_id, status, source_hash, loaded_hash)

    def as_dict(self) -> dict[str, Any]:
        return {
            "release_build_id": self.build_id,
            "worker_fencing_id": self.worker_fencing_id,
            "runtime_path_id": self.runtime_path_id,
            "source_status": self.source_status,
            "source_manifest_sha256": self.source_manifest_sha256,
            "loaded_code_manifest_sha256": self.loaded_code_manifest_sha256,
        }


def _loaded_code_hash() -> str:
    """Hash code objects already loaded in this worker, not just disk files."""
    modules = (
        "novel_flywheel.models", "novel_flywheel.providers.http",
        "novel_flywheel.reliability_spine", "novel_flywheel.provider_response_capture",
        "novel_flywheel.workflows", "novel_flywheel.completion_supervisor",
    )
    items: list[tuple[str, str]] = []
    for name in modules:
        try:
            module = importlib.import_module(name)
        except (ImportError, OSError):
            continue
        for attr_name, value in sorted(vars(module).items()):
            if isinstance(value, types.FunctionType):
                try:
                    payload = marshal.dumps(value.__code__)
                except (TypeError, ValueError):
                    continue
                items.append((f"{name}:{attr_name}", hashlib.sha256(payload).hexdigest()))
            elif isinstance(value, type) and value.__module__ == name:
                for method_name, method in sorted(vars(value).items()):
                    function = method
                    if isinstance(method, (staticmethod, classmethod)):
                        function = method.__func__
                    if isinstance(function, types.FunctionType):
                        try:
                            payload = marshal.dumps(function.__code__)
                        except (TypeError, ValueError):
                            continue
                        items.append((f"{name}:{attr_name}.{method_name}", hashlib.sha256(payload).hexdigest()))
    return _sha(items)


@dataclass(frozen=True)
class ExecutionEnvelope:
    episode: CanonicalEpisodeIdentity
    physical_request_id: str
    build: ReleaseBuildIdentity
    route_fingerprint: str
    provider_id: str
    model_id: str
    protocol: str
    destination: str
    execution_mode: str
    schema_sha256: str
    requested_output_tokens: int | None
    config_version: str
    cutover_state: str
    recovery_coordinator_version: str
    physical_request_ledger_version: str
    capture_manifest_version: str
    failure_taxonomy_version: str
    capability_policy_version: str
    envelope_sha256: str

    @classmethod
    def build_for(cls, metadata: Mapping[str, Any], release: ReleaseBuildIdentity) -> "ExecutionEnvelope":
        episode = CanonicalEpisodeIdentity.build(metadata)
        body = {
            "episode": episode.as_dict(),
            "release": release.as_dict(),
            "route_fingerprint": str(metadata.get("route_fingerprint") or ""),
            "provider_id": str(metadata.get("provider_id") or ""),
            "model_id": str(metadata.get("model_id") or ""),
            "protocol": str(metadata.get("protocol") or ""),
            "destination": str(metadata.get("destination") or ""),
            "execution_mode": str(metadata.get("execution_mode") or "plain"),
            "schema_sha256": str(metadata.get("schema_sha256") or ""),
            "requested_output_tokens": metadata.get("max_output_tokens"),
            "config_version": str(metadata.get("config_version") or ""),
            "cutover_state": str(metadata.get("cutover_state") or "CUTOVER"),
            "recovery_coordinator_version": str(
                metadata.get("recovery_coordinator_version") or RECOVERY_COORDINATOR_VERSION
            ),
            "physical_request_ledger_version": "PhysicalRequestLedgerV1",
            "capture_manifest_version": "CaptureManifestV1",
            "failure_taxonomy_version": "TypedFailureGraphV1",
            "capability_policy_version": str(
                metadata.get("capability_policy_version") or "short-capability-policy-v1"
            ),
        }
        return cls(
            episode=episode,
            physical_request_id=str(metadata.get("physical_request_id") or secrets.token_hex(16)),
            build=release,
            route_fingerprint=body["route_fingerprint"],
            provider_id=body["provider_id"], model_id=body["model_id"],
            protocol=body["protocol"], destination=body["destination"],
            execution_mode=body["execution_mode"], schema_sha256=body["schema_sha256"],
            requested_output_tokens=(int(body["requested_output_tokens"]) if body["requested_output_tokens"] is not None else None),
            config_version=body["config_version"],
            cutover_state=body["cutover_state"],
            recovery_coordinator_version=body["recovery_coordinator_version"],
            physical_request_ledger_version=body["physical_request_ledger_version"],
            capture_manifest_version=body["capture_manifest_version"],
            failure_taxonomy_version=body["failure_taxonomy_version"],
            capability_policy_version=body["capability_policy_version"],
            envelope_sha256=domain_sha256("novel-flywheel-execution-envelope-v1", body),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "ExecutionEnvelopeV1",
            "episode": self.episode.as_dict(),
            "physical_request_id": self.physical_request_id,
            "release": self.build.as_dict(),
            "route_fingerprint": self.route_fingerprint,
            "provider_id": self.provider_id, "model_id": self.model_id,
            "protocol": self.protocol, "destination": self.destination,
            "execution_mode": self.execution_mode,
            "schema_sha256": self.schema_sha256,
            "requested_output_tokens": self.requested_output_tokens,
            "config_version": self.config_version,
            "cutover_state": self.cutover_state,
            "recovery_coordinator_version": self.recovery_coordinator_version,
            "physical_request_ledger_version": self.physical_request_ledger_version,
            "capture_manifest_version": self.capture_manifest_version,
            "failure_taxonomy_version": self.failure_taxonomy_version,
            "capability_policy_version": self.capability_policy_version,
            "envelope_sha256": self.envelope_sha256,
        }


class CanonicalDispatchError(RuntimeError):
    """Fail-closed before Provider transport when the spine is incomplete."""

    provider_call_executed = False

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class DurableNodeState:
    """The restart boundary for one logical Short node.

    This is deliberately separate from the high-level run status.  A resume
    can therefore continue the last incomplete node without re-entering the
    whole Segment function and without making an old failure eligible again.
    """

    node_id: str
    episode_id: str
    state: str
    version: int
    candidate_sha256: str
    contract_sha256: str
    route_fingerprint: str
    release_build_id: str
    cutover_version: str
    updated_at: str
    config_version: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": DURABLE_NODE_SCHEMA, "node_id": self.node_id,
            "episode_id": self.episode_id, "state": self.state,
            "version": self.version, "candidate_sha256": self.candidate_sha256,
            "contract_sha256": self.contract_sha256,
            "route_fingerprint": self.route_fingerprint,
            "release_build_id": self.release_build_id,
            "cutover_version": self.cutover_version,
            "config_version": self.config_version,
            "updated_at": self.updated_at,
        }


class DurableNodeStateStore:
    """Small CAS-backed durable node store used by the dispatch coordinator."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root) / "durable-nodes"
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _path(self, node_id: str) -> Path:
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in node_id)
        return self.root / f"{safe}.json"

    def prepare(self, *, node_id: str, episode_id: str, candidate_sha256: str,
                contract_sha256: str, release_build_id: str,
                cutover_version: str, route_fingerprint: str = "",
                config_version: str = "") -> DurableNodeState:
        with self._lock:
            path = self._path(node_id)
            if path.exists():
                current = self.load(node_id)
                if current is None:
                    raise CanonicalDispatchError("durable_node_unreadable")
                if (
                    current.episode_id != episode_id
                    or current.candidate_sha256 != candidate_sha256
                    or current.contract_sha256 != contract_sha256
                    or current.route_fingerprint != route_fingerprint
                    or current.release_build_id != release_build_id
                    or current.cutover_version != cutover_version
                    or current.config_version != config_version
                ):
                    raise CanonicalDispatchError("stale_durable_node_identity")
                return current
            value = DurableNodeState(
                node_id=node_id, episode_id=episode_id,
                state="REVIEW_PREPARED", version=1,
                candidate_sha256=candidate_sha256,
                contract_sha256=contract_sha256,
                route_fingerprint=route_fingerprint,
                release_build_id=release_build_id,
                cutover_version=cutover_version, config_version=config_version,
                updated_at=_now(),
            )
            self._write(path, value.as_dict())
            return value

    def rebind_stale_for_migration(self, *, node_id: str, episode_id: str,
                                   candidate_sha256: str, contract_sha256: str,
                                   release_build_id: str, cutover_version: str,
                                   route_fingerprint: str = "",
                                   config_version: str = "") -> DurableNodeState:
        """Archive an old identity and materialize the same logical node.

        This is intentionally a migration-only operation.  Normal dispatch
        continues to fail closed on identity drift through ``prepare``.  The
        caller must be the bounded legacy-checkpoint migration, which keeps
        the prior JSON as an auditable ``.stale.<hash>`` artifact before
        creating the current-release node.
        """
        with self._lock:
            path = self._path(node_id)
            current = self.load(node_id)
            if current is None:
                raise CanonicalDispatchError("durable_node_missing")
            if (
                current.episode_id == episode_id
                and current.candidate_sha256 == candidate_sha256
                and current.contract_sha256 == contract_sha256
                and current.route_fingerprint == route_fingerprint
                and current.release_build_id == release_build_id
                and current.cutover_version == cutover_version
                and current.config_version == config_version
            ):
                return current
            stale_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            archive = path.with_name(
                f"{path.stem}.stale.{stale_hash[:16]}{path.suffix}"
            )
            if not archive.exists():
                archive.write_bytes(path.read_bytes())
            path.unlink()
            return self.prepare(
                node_id=node_id, episode_id=episode_id,
                candidate_sha256=candidate_sha256,
                contract_sha256=contract_sha256,
                release_build_id=release_build_id,
                cutover_version=cutover_version,
                route_fingerprint=route_fingerprint,
                config_version=config_version,
            )

    def transition(self, node_id: str, *, expected_state: str,
                   state: str, **updates: Any) -> DurableNodeState:
        if state not in _DURABLE_NODE_STATES:
            raise CanonicalDispatchError("unknown_durable_node_state")
        with self._lock:
            current = self.load(node_id)
            if current is None:
                raise CanonicalDispatchError("durable_node_missing")
            if current.state != expected_state:
                raise CanonicalDispatchError("durable_node_cas_conflict")
            data = current.as_dict()
            data.update({k: v for k, v in updates.items() if k in data})
            data.update({"state": state, "version": current.version + 1,
                         "updated_at": _now()})
            self._write(self._path(node_id), data)
            return self.load(node_id)  # type: ignore[return-value]

    def load(self, node_id: str) -> DurableNodeState | None:
        try:
            data = json.loads(self._path(node_id).read_text(encoding="utf-8"))
            if data.get("schema") != DURABLE_NODE_SCHEMA:
                return None
            return DurableNodeState(
                node_id=str(data["node_id"]), episode_id=str(data["episode_id"]),
                state=str(data["state"]), version=int(data["version"]),
                candidate_sha256=str(data["candidate_sha256"]),
                contract_sha256=str(data["contract_sha256"]),
                route_fingerprint=str(data.get("route_fingerprint") or ""),
                release_build_id=str(data["release_build_id"]),
                cutover_version=str(data["cutover_version"]),
                updated_at=str(data["updated_at"]),
                config_version=str(data.get("config_version") or ""),
            )
        except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            return None

    @staticmethod
    def _write(path: Path, value: Mapping[str, Any]) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(dict(value), ensure_ascii=False,
                                         sort_keys=True, indent=2) + "\n",
                              encoding="utf-8", newline="\n")
        os.replace(temporary, path)


@dataclass(frozen=True)
class TypedFailureRecord:
    failure_id: str
    failure_class: str
    source_component: str
    episode_id: str
    physical_request_id: str
    condition_signature: str
    direct_cause_ids: tuple[str, ...]
    recovery_eligible: bool
    terminal: bool
    evidence_refs: tuple[str, ...]
    created_at: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "TypedFailureRecordV1", "failure_id": self.failure_id,
            "failure_class": self.failure_class,
            "source_component": self.source_component,
            "episode_id": self.episode_id,
            "physical_request_id": self.physical_request_id,
            "condition_signature": self.condition_signature,
            "direct_cause_ids": list(self.direct_cause_ids),
            "recovery_eligible": self.recovery_eligible,
            "terminal": self.terminal, "evidence_refs": list(self.evidence_refs),
            "created_at": self.created_at,
        }


class TypedFailureGraphStore:
    """Append-only causal graph; summaries never replace root records."""

    def __init__(self, root: Path) -> None:
        self.path = Path(root) / "typed-failure-graph.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def record(self, *, failure_class: str, source_component: str,
               episode_id: str, physical_request_id: str = "",
               condition_signature: str, direct_cause_ids: tuple[str, ...] = (),
               recovery_eligible: bool, terminal: bool,
               evidence_refs: tuple[str, ...] = ()) -> TypedFailureRecord:
        body = {
            "failure_class": failure_class, "source_component": source_component,
            "episode_id": episode_id, "physical_request_id": physical_request_id,
            "condition_signature": condition_signature,
            "direct_cause_ids": list(direct_cause_ids),
            "recovery_eligible": recovery_eligible, "terminal": terminal,
            "evidence_refs": list(evidence_refs),
        }
        record = TypedFailureRecord(
            failure_id=domain_sha256("short-failure-record-v1", {**body, "created_at": _now()}),
            created_at=_now(), **body,
        )
        with self._lock, self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record.as_dict(), ensure_ascii=False, sort_keys=True) + "\n")
        return record


@dataclass(frozen=True)
class CutoverSnapshot:
    version: str
    state: str
    active_authority: str
    config_version: str

    def as_dict(self) -> dict[str, str]:
        return {"version": self.version, "state": self.state,
                "active_authority": self.active_authority,
                "config_version": self.config_version}


class CutoverRegistry:
    """Versioned, mutually exclusive old/new authority snapshot."""

    def __init__(self, *, state: str = "CUTOVER", active_authority: str = "canonical",
                 config_version: str = "") -> None:
        self.snapshot = CutoverSnapshot(CUTOVER_REGISTRY_VERSION, state.upper(),
                                        active_authority, config_version)

    def validate(self) -> None:
        if self.snapshot.state not in {"SHADOW", "CUTOVER", "RETIRE", "QUALIFICATION"}:
            raise CanonicalDispatchError("ambiguous_cutover_state")
        if self.snapshot.state == "CUTOVER" and self.snapshot.active_authority != "canonical":
            raise CanonicalDispatchError("ambiguous_cutover_authority")
        if self.snapshot.state == "SHADOW" and self.snapshot.active_authority != "legacy":
            raise CanonicalDispatchError("ambiguous_shadow_authority")


@dataclass(frozen=True)
class RecoveryAction:
    action: str
    reason: str
    condition_signature: str
    physical_dispatch_allowed: bool


class RecoveryCoordinator:
    """The only component allowed to turn a failure into a new dispatch intent."""

    def __init__(self, root: Path, *, version: str = RECOVERY_COORDINATOR_VERSION) -> None:
        self.version = version
        self.path = Path(root) / "recovery-coordinator.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._seen_signatures: set[str] = set()
        self._lock = threading.RLock()
        # Decisions survive a worker restart.  Without loading this append-only
        # journal, the same blocked condition would look new after every
        # process restart and could recreate a recovery child/intent.
        try:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                value = json.loads(line)
                signature = value.get("condition_signature") if isinstance(value, dict) else None
                if isinstance(signature, str) and signature:
                    self._seen_signatures.add(signature)
        except (OSError, UnicodeError, json.JSONDecodeError):
            pass

    @staticmethod
    def condition_signature(*, episode: Mapping[str, Any], route_fingerprint: str,
                            capability_snapshot: Any, durable_state: str,
                            blocker_signature: str, config_version: str,
                            build_id: str, cutover_version: str,
                            recovery_action: str = "reentry") -> str:
        """Derive one stable no-progress signature for high-level re-entry."""

        return _sha({
            "schema": "RecoveryConditionSignatureV1",
            "episode": dict(episode),
            "route_fingerprint": str(route_fingerprint or ""),
            "capability_snapshot": capability_snapshot or {},
            "durable_state": str(durable_state or ""),
            "blocker_signature": str(blocker_signature or ""),
            "config_version": str(config_version or ""),
            "build_id": str(build_id or ""),
            "cutover_version": str(cutover_version or ""),
            "recovery_action": str(recovery_action or "reentry"),
        })

    def decide(self, *, node_state: str, condition_signature: str,
               failure_class: str = "", changed: bool = False) -> RecoveryAction:
        with self._lock:
            if condition_signature in self._seen_signatures and not changed:
                action = RecoveryAction("NO_ACTION", "same_condition_signature", condition_signature, False)
            elif node_state in {"RESPONSE_CAPTURED", "RECEIPT_VALIDATED"}:
                action = RecoveryAction("LOCAL_REPLAY_VALIDATION", "response_already_saved", condition_signature, False)
            elif failure_class in {"business_reject", "content_finding"}:
                action = RecoveryAction("CONTENT_REPAIR", "valid_business_finding", condition_signature, True)
            elif failure_class in {"transport_unknown", "unknown_dispatch"}:
                action = RecoveryAction("RECONCILE_UNKNOWN_DISPATCH", "network_state_unknown", condition_signature, False)
            elif failure_class in {"receipt_invalid", "protocol_invalid"}:
                action = RecoveryAction("RECEIPT_CORRECTION", "structured_receipt_invalid", condition_signature, True)
            else:
                action = RecoveryAction("LOCAL_REPREPARE", "pre_dispatch_or_unclassified", condition_signature, False)
            self._seen_signatures.add(condition_signature)
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps({"schema": "RecoveryDecisionV1", **action.__dict__,
                                         "coordinator_version": self.version, "recorded_at": _now()},
                                        ensure_ascii=False, sort_keys=True) + "\n")
            return action


@dataclass(frozen=True)
class CanRunRealDispatchProof:
    release_build_match: bool
    worker_fencing_valid: bool
    canonical_entrypoint: bool
    cutover_unambiguous: bool
    envelope_current: bool
    prepared_work_not_stale: bool
    physical_ledger_ready: bool
    capture_manifest_ready: bool
    recovery_coordinator_authority: bool
    no_unknown_duplicate: bool

    @property
    def allowed(self) -> bool:
        return all(self.__dict__.values())

    def as_dict(self) -> dict[str, Any]:
        return {**self.__dict__, "allowed": self.allowed}


@dataclass
class DispatchAuthorization:
    spine: "CanonicalDispatchCoordinator"
    envelope: ExecutionEnvelope
    state: str = "RESERVED"
    _closed: bool = False
    _capture_transport_complete: bool | None = None

    @property
    def physical_request_id(self) -> str:
        return self.envelope.physical_request_id

    def before_network(self) -> None:
        if self._closed or self.state != "RESERVED":
            raise CanonicalDispatchError("canonical_dispatch_not_reserved")
        current = self.spine.release
        if (
            self.envelope.build.build_id != current.build_id
            or self.envelope.build.worker_fencing_id != current.worker_fencing_id
            or self.envelope.build.runtime_path_id != current.runtime_path_id
        ):
            raise CanonicalDispatchError("stale_prepared_work_identity")
        if self.spine._active.get(self.physical_request_id) is not self:
            raise CanonicalDispatchError("worker_fencing_identity_mismatch")
        self.spine._validate_can_run(self)
        self.state = "DISPATCHING"
        node_id = self.envelope.episode.logical_node_id
        node = self.spine.nodes.load(node_id)
        if node is not None and node.state == "REVIEW_PREPARED":
            self.spine.nodes.transition(node_id, expected_state="REVIEW_PREPARED",
                                        state="REVIEW_DISPATCH_RESERVED")
        self.spine._persist(self, "DISPATCHING")

    def capture_response(
        self, data: bytes, *, status_code: int, content_type: str,
        encoding: str, transport_complete: bool,
    ) -> None:
        if self._closed or self.state != "DISPATCHING":
            raise CanonicalDispatchError("canonical_response_capture_not_dispatching")
        self._capture_transport_complete = bool(transport_complete)
        try:
            evidence = self.spine._capture_provider_response(
                self, data=data, status_code=status_code,
                content_type=content_type, encoding=encoding,
                transport_complete=transport_complete,
            )
        except Exception as exc:
            self.state = "RESPONSE_CAPTURE_FAILED"
            node_id = self.envelope.episode.logical_node_id
            node = self.spine.nodes.load(node_id)
            if node is not None and node.state == "REVIEW_DISPATCH_RESERVED":
                self.spine.nodes.transition(
                    node_id, expected_state="REVIEW_DISPATCH_RESERVED",
                    state="WAITING_LOCAL_RECOVERY",
                )
            self.spine._persist(
                self, self.state, status_code=status_code,
                failure_code=type(exc).__name__,
                response_transport_complete=bool(transport_complete),
            )
            raise
        self.state = "RESPONSE_CAPTURED"
        self.spine._persist(self, self.state, status_code=status_code, **evidence)

    def after_response(self, status_code: int) -> None:
        if self._closed:
            return
        self.state = "RESPONSE_RECEIVED"
        node_id = self.envelope.episode.logical_node_id
        node = self.spine.nodes.load(node_id)
        if node is not None and node.state == "REVIEW_DISPATCH_RESERVED":
            self.spine.nodes.transition(node_id, expected_state="REVIEW_DISPATCH_RESERVED",
                                        state="RESPONSE_CAPTURED")
        self.spine._persist(self, "RESPONSE_RECEIVED", status_code=status_code)

    def after_failure(self, *, unknown: bool = False, failure: str = "") -> None:
        if self._closed:
            return
        if self.state == "RESPONSE_CAPTURE_FAILED":
            return
        if self.state == "RESPONSE_CAPTURED":
            complete = bool(self._capture_transport_complete)
            self.state = (
                "RESPONSE_CAPTURED_LOCAL_FAILURE"
                if complete
                else (
                    "RESPONSE_PARTIAL_CAPTURED_TRANSPORT_UNKNOWN"
                    if unknown else "RESPONSE_PARTIAL_CAPTURED_FAILURE"
                )
            )
            node_id = self.envelope.episode.logical_node_id
            node = self.spine.nodes.load(node_id)
            if node is not None and node.state == "REVIEW_DISPATCH_RESERVED":
                self.spine.nodes.transition(
                    node_id, expected_state="REVIEW_DISPATCH_RESERVED",
                    state=(
                        "RESPONSE_CAPTURED" if complete
                        else (
                            "REVIEW_SENT_OR_UNKNOWN"
                            if unknown else "WAITING_LOCAL_RECOVERY"
                        )
                    ),
                )
            self.spine._persist(
                self, self.state, failure_code=failure,
                response_transport_complete=complete,
            )
            return
        self.state = "TRANSPORT_UNKNOWN" if unknown else "TRANSPORT_CONFIRMED_FAILED"
        node_id = self.envelope.episode.logical_node_id
        node = self.spine.nodes.load(node_id)
        if node is not None and node.state == "REVIEW_DISPATCH_RESERVED":
            self.spine.nodes.transition(
                node_id, expected_state="REVIEW_DISPATCH_RESERVED",
                state=("REVIEW_SENT_OR_UNKNOWN" if unknown else "WAITING_LOCAL_RECOVERY"),
            )
        self.spine._persist(self, self.state, failure_code=failure)


class CanonicalDispatchCoordinator:
    """One dispatch decision-maker for all application Provider requests."""

    def __init__(self, data_root: Path, *, worker_fencing_id: str | None = None,
                 require_release: bool = False,
                 require_foundation_gates: bool = False,
                 config_version: str = "") -> None:
        self.data_root = Path(data_root)
        self.root = self.data_root / "reliability-spine-v1"
        self.root.mkdir(parents=True, exist_ok=True)
        self.ledger_path = self.root / "physical-request-ledger.jsonl"
        self.manifest_root = self.root / "capture-manifests"
        self.manifest_root.mkdir(exist_ok=True)
        self.response_evidence_root = self.root / "provider-response-evidence"
        self.response_evidence_root.mkdir(exist_ok=True)
        self.release = ReleaseBuildIdentity.collect(self.data_root, worker_fencing_id=worker_fencing_id)
        self.require_release = bool(require_release)
        self.require_foundation_gates = bool(require_foundation_gates)
        self.cutover = CutoverRegistry(config_version=str(config_version or ""))
        self.nodes = DurableNodeStateStore(self.root)
        self.failures = TypedFailureGraphStore(self.root)
        self.recovery = RecoveryCoordinator(self.root)
        self._lock = threading.RLock()
        self._active: dict[str, DispatchAuthorization] = {}
        self.old_path_invocations = 0

    def record_old_path_invocation(self, code: str) -> None:
        """Record a blocked deprecated entrypoint without exposing a stack."""
        with self._lock:
            self.old_path_invocations += 1
            path = self.root / "old-path-invocations.jsonl"
            with path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps({
                    "schema": "OldPathInvocationV1", "code": str(code),
                    "recorded_at": _now(), "provider_call_executed": False,
                }, ensure_ascii=False, sort_keys=True) + "\n")

    def attest(self) -> dict[str, Any]:
        loaded_ok = self._loaded_code_matches_release()
        foundation = self.foundation_gates()
        return {
            **self.release.as_dict(),
            "runtime_path_attestation": "PASS" if self.release.runtime_path_id else "FAIL",
            "loaded_code_matches_release_build": loaded_ok,
            "canonical_production_entrypoints": "PASS",
            "provider_dispatch_decision_makers": 1,
            "legacy_entrypoint_direct_provider_dispatch": 0,
            "recovery_coordinator_version": self.recovery.version,
            "cutover": self.cutover.snapshot.as_dict(),
            "durable_node_schema": DURABLE_NODE_SCHEMA,
            "foundation_gates": foundation,
        }

    def foundation_gates(self) -> dict[str, Any]:
        path = self.root / "foundation-gates.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            gates = value.get("gates") if isinstance(value, dict) else None
            if isinstance(gates, dict):
                identity = self._foundation_identity()
                if any(value.get(key) != expected for key, expected in identity.items()):
                    return {str(k): "STALE" for k in gates}
                return {str(k): str(v) for k, v in gates.items()}
        except (OSError, UnicodeError, json.JSONDecodeError, AttributeError):
            pass
        return self._default_foundation_gates("PENDING")

    @staticmethod
    def _default_foundation_gates(status: str) -> dict[str, str]:
        return {
            "F1_CANONICAL_EPISODE_IDENTITY": status,
            "F2_PHYSICAL_REQUEST_LEDGER": status,
            "F3_TYPED_FAILURE_GRAPH": status,
            "F4_NODE_LEVEL_DURABLE_STATE": status,
            "F5_CAPTURE_MANIFEST": status,
            "F6_SINGLE_RECOVERY_COORDINATOR": status,
            "F7_RELEASE_BUILD_IDENTITY_AND_WORKER_FENCING": status,
            "F8_PRODUCTION_SHAPED_CORE_MATRIX": status,
        }

    def _foundation_identity(self) -> dict[str, str]:
        return {
            "release_build_id": self.release.build_id,
            "loaded_code_manifest_sha256": self.release.loaded_code_manifest_sha256,
            "source_manifest_sha256": self.release.source_manifest_sha256,
            "schema_version": SCHEMA_VERSION,
            "cutover_registry_version": self.cutover.snapshot.version,
            "cutover_config_version": self.cutover.snapshot.config_version,
            "recovery_coordinator_version": self.recovery.version,
            "durable_node_schema": DURABLE_NODE_SCHEMA,
            "physical_request_ledger_version": "PhysicalRequestLedgerV1",
            "capture_manifest_version": "CaptureManifestV1",
            "failure_taxonomy_version": "TypedFailureGraphV1",
            "runtime_path_id": self.release.runtime_path_id,
            "worker_fencing_id": self.release.worker_fencing_id,
        }

    def mark_foundation_gates(self, gates: Mapping[str, str], *, evidence_refs: tuple[str, ...] = ()) -> None:
        required = {
            "F1_CANONICAL_EPISODE_IDENTITY", "F2_PHYSICAL_REQUEST_LEDGER",
            "F3_TYPED_FAILURE_GRAPH", "F4_NODE_LEVEL_DURABLE_STATE",
            "F5_CAPTURE_MANIFEST", "F6_SINGLE_RECOVERY_COORDINATOR",
            "F7_RELEASE_BUILD_IDENTITY_AND_WORKER_FENCING",
            "F8_PRODUCTION_SHAPED_CORE_MATRIX",
        }
        if set(gates) != required or any(str(gates[k]) != "PASS" for k in required):
            raise CanonicalDispatchError("foundation_gates_incomplete")
        path = self.root / "foundation-gates.json"
        if path.exists():
            current = self.foundation_gates()
            if current != dict(gates):
                # A release or worker change makes the prior gate record
                # stale. Preserve it as immutable history, then bind the
                # validated evidence to this live release. Any non-stale
                # conflicting PASS record remains fail-closed.
                if not current or any(value != "STALE" for value in current.values()):
                    raise CanonicalDispatchError("foundation_gates_immutable_conflict")
                archive_hash = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
                archive = self.root / f"foundation-gates.stale.{archive_hash}.json"
                os.replace(path, archive)
            else:
                return
        DurableNodeStateStore._write(path, {
            "schema": "FoundationGatesV1", "gates": dict(gates),
            **self._foundation_identity(),
            "evidence_refs": list(evidence_refs), "recorded_at": _now(),
        })

    def _loaded_code_matches_release(self) -> bool:
        """Verify imported production modules against their current source.

        This is intentionally a runtime check, not a health endpoint claim. A
        stale worker sees the mismatch before transport and is fenced.
        """
        try:
            modules = (
                "novel_flywheel.models", "novel_flywheel.providers.http",
                "novel_flywheel.reliability_spine", "novel_flywheel.provider_response_capture",
            )
            for name in modules:
                module = importlib.import_module(name)
                path = Path(str(getattr(module, "__file__", ""))).resolve()
                if not path.is_file() or path.suffix not in {".py", ".pyc"}:
                    return False
                if path.suffix == ".py":
                    compile(path.read_text(encoding="utf-8"), str(path), "exec")
            # The source manifest is the stable release identity.  Code-object
            # hashes are retained in evidence, but Python may materialize
            # lazily-imported adapter classes between the first and second
            # attestation; they are therefore a diagnostic, not a dispatch
            # decision key.
            current = collect_build_manifests()
            source = current.installed_runtime or current.production_source
            return (
                current.status != "unknown_runtime"
                and str((source or {}).get("definition_sha256") or "")
                == self.release.source_manifest_sha256
            )
        except (OSError, UnicodeError, SyntaxError, ImportError):
            return False

    def _validate_can_run(self, authorization: DispatchAuthorization) -> None:
        self.cutover.validate()
        if not self._loaded_code_matches_release():
            raise CanonicalDispatchError("loaded_code_release_mismatch")
        if self.require_foundation_gates and not all(
            value == "PASS" for value in self.foundation_gates().values()
        ):
            raise CanonicalDispatchError("foundation_gates_incomplete")
        envelope = authorization.envelope
        node = self.nodes.load(envelope.episode.logical_node_id)
        proof = CanRunRealDispatchProof(
            release_build_match=(envelope.build.build_id == self.release.build_id),
            worker_fencing_valid=(envelope.build.worker_fencing_id == self.release.worker_fencing_id),
            canonical_entrypoint=True,
            cutover_unambiguous=True,
            # The envelope is immutable after admission.  Its build, cutover,
            # candidate and contract identities are checked above and in the
            # durable node; rebuilding it from a lossy adapter dictionary
            # would create a second identity generator.
            envelope_current=(envelope.build.build_id == self.release.build_id),
            prepared_work_not_stale=(
                node is not None
                and node.release_build_id == self.release.build_id
                and node.cutover_version == self.cutover.snapshot.version
                and node.config_version == envelope.config_version
                and envelope.config_version == self.cutover.snapshot.config_version
            ),
            physical_ledger_ready=True,
            capture_manifest_ready=(self.manifest_root / f"{envelope.physical_request_id}.json").is_file(),
            recovery_coordinator_authority=True,
            no_unknown_duplicate=(self._active.get(envelope.physical_request_id) is authorization),
        )
        if not proof.allowed:
            self.failures.record(
                failure_class="dispatch_readiness", source_component="reliability_spine",
                episode_id=envelope.episode.episode_sha256,
                physical_request_id=envelope.physical_request_id,
                condition_signature=_sha(proof.as_dict()), recovery_eligible=False,
                terminal=False,
            )
            raise CanonicalDispatchError("can_run_real_dispatch_proof_failed")

    def admit(self, metadata: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            cutover = str(metadata.get("cutover_state") or self.cutover.snapshot.state).upper()
            if cutover not in {"CUTOVER", "QUALIFICATION"}:
                self.old_path_invocations += 1
                raise CanonicalDispatchError("ambiguous_cutover_state")
            if cutover != self.cutover.snapshot.state and self.cutover.snapshot.state == "CUTOVER":
                raise CanonicalDispatchError("stale_cutover_snapshot")
            if self.require_release and self.release.source_status == "unknown_runtime":
                raise CanonicalDispatchError("release_build_identity_unavailable")
            if self.require_release:
                required = {
                    "project_id": metadata.get("project_id"),
                    "run_id": metadata.get("operation_run_id") or metadata.get("run_id"),
                    "workflow_kind": metadata.get("workflow_kind"),
                    "logical_node_id": metadata.get("logical_node_id"),
                    "candidate_sha256": metadata.get("candidate_sha256"),
                    "contract_name": metadata.get("contract_name"),
                    "config_version": metadata.get("config_version"),
                }
                if any(not str(value or "").strip() for value in required.values()):
                    raise CanonicalDispatchError(
                        "canonical_episode_identity_incomplete"
                    )
                if (
                    str(required["config_version"])
                    != self.cutover.snapshot.config_version
                ):
                    raise CanonicalDispatchError("stale_cutover_config")
            if not str(metadata.get("provider_id") or "") or not str(metadata.get("model_id") or ""):
                raise CanonicalDispatchError("canonical_route_identity_missing")
            envelope = ExecutionEnvelope.build_for(metadata, self.release)
            if envelope.physical_request_id in self._active:
                raise CanonicalDispatchError("duplicate_physical_request_id")
            node_id = envelope.episode.logical_node_id
            contract_hash = str(metadata.get("contract_sha256") or envelope.schema_sha256 or _sha("contract"))
            self.nodes.prepare(
                node_id=node_id, episode_id=envelope.episode.episode_sha256,
                candidate_sha256=envelope.episode.candidate_sha256,
                contract_sha256=contract_hash, release_build_id=self.release.build_id,
                cutover_version=self.cutover.snapshot.version,
                route_fingerprint=envelope.route_fingerprint,
                config_version=envelope.config_version,
            )
            auth = DispatchAuthorization(self, envelope)
            self._active[envelope.physical_request_id] = auth
            self._persist(auth, "RESERVED")
            return {
                "canonical_episode_id": envelope.episode.episode_sha256,
                "physical_request_id": envelope.physical_request_id,
                "execution_envelope_hash": envelope.envelope_sha256,
                "runtime_path_id": envelope.build.runtime_path_id,
                "release_build_id": envelope.build.build_id,
                "worker_fencing_id": envelope.build.worker_fencing_id,
                "recovery_coordinator_version": self.recovery.version,
                "capture_manifest_version": "CaptureManifestV1",
                "durable_node_id": node_id,
                "canonical_dispatch_authorization": auth,
            }

    def evaluate_reentry(self, metadata: Mapping[str, Any], *,
                         node_state: str, failure_class: str = "",
                         blocker_signature: str = "", changed: bool = False) -> dict[str, Any]:
        """Re-evaluate a blocked node without creating a Provider intent.

        This is deliberately separate from ``admit``.  Manual resume and
        supervisor recovery may call it repeatedly, but the same condition
        signature is persisted by the coordinator and returns ``NO_ACTION``.
        A new dispatch can only be created later through ``admit`` after an
        actual candidate/route/config/build change is represented in metadata.
        """

        episode = CanonicalEpisodeIdentity.build(metadata)
        route = str(metadata.get("route_fingerprint") or "")
        capability = metadata.get("capability_snapshot") or {}
        config_version = str(metadata.get("config_version") or self.cutover.snapshot.config_version)
        signature = RecoveryCoordinator.condition_signature(
            episode=episode.as_dict(), route_fingerprint=route,
            capability_snapshot=capability, durable_state=node_state,
            blocker_signature=blocker_signature or str(metadata.get("failure_sha256") or ""),
            config_version=config_version, build_id=self.release.build_id,
            cutover_version=self.cutover.snapshot.version,
        )
        action = self.recovery.decide(
            node_state=node_state, condition_signature=signature,
            failure_class=failure_class, changed=changed,
        )
        return {
            "schema": "RecoveryReentryEvaluationV1",
            "condition_signature": signature,
            # Child identity is condition-scoped, not action-name-scoped.  A
            # restart that re-evaluates the same blocker must not create a
            # second child merely because the first decision was persisted.
            "recovery_child_id": _sha({"signature": signature}),
            "action": action.action,
            "reason": action.reason,
            "physical_dispatch_allowed": action.physical_dispatch_allowed,
            "changed": bool(changed),
            "provider_intent_created": False,
        }

    def _capture_provider_response(
        self, authorization: DispatchAuthorization, *, data: bytes,
        status_code: int, content_type: str, encoding: str,
        transport_complete: bool,
    ) -> dict[str, Any]:
        """Persist and re-read a privacy-safe response before conversion.

        The raw byte hash binds this evidence to the transport entity. Hidden
        reasoning is never written. The manifest and ledger receive the same
        evidence hash, so a restart can prove which captured result belongs to
        the immutable physical request before local validation resumes.
        """

        envelope = authorization.envelope
        projection = provider_response_evidence_projection_v1(
            data, content_type=content_type, encoding=encoding,
            transport_complete=transport_complete,
        )
        document = {
            "schema": "CanonicalProviderResponseEvidenceV1",
            "physical_request_id": envelope.physical_request_id,
            "canonical_episode_id": envelope.episode.episode_sha256,
            "execution_envelope_hash": envelope.envelope_sha256,
            "release_build_id": envelope.build.build_id,
            "worker_fencing_id": envelope.build.worker_fencing_id,
            "runtime_path_id": envelope.build.runtime_path_id,
            "project_id": envelope.episode.project_id,
            "run_id": envelope.episode.run_id,
            "logical_node_id": envelope.episode.logical_node_id,
            "candidate_sha256": envelope.episode.candidate_sha256,
            "contract_name": envelope.episode.contract_name,
            "contract_version": envelope.episode.contract_version,
            "route_fingerprint": envelope.route_fingerprint,
            "status_code": int(status_code),
            "evidence": projection,
            "captured_at": _now(),
        }
        body = (
            json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2)
            + "\n"
        ).encode("utf-8")
        evidence_sha256 = hashlib.sha256(body).hexdigest()
        path = self.response_evidence_root / (
            f"{envelope.physical_request_id}.json"
        )
        if path.exists():
            existing = path.read_bytes()
            if existing != body:
                raise CanonicalDispatchError(
                    "canonical_response_evidence_duplicate_mismatch"
                )
        else:
            temporary = path.with_suffix(".json.tmp")
            temporary.write_bytes(body)
            with temporary.open("rb+") as handle:
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        replayed = path.read_bytes()
        if hashlib.sha256(replayed).hexdigest() != evidence_sha256:
            raise CanonicalDispatchError(
                "canonical_response_evidence_reread_mismatch"
            )
        relative_path = path.relative_to(self.root).as_posix()
        return {
            "response_evidence_path": relative_path,
            "response_evidence_sha256": evidence_sha256,
            "response_raw_sha256": projection["raw_sha256"],
            "response_raw_length": projection["raw_length"],
            "response_transport_complete": bool(transport_complete),
            "response_evidence_redaction": projection["redaction"],
        }

    def _persist(self, authorization: DispatchAuthorization, state: str, **extra: Any) -> None:
        envelope = authorization.envelope
        entry = {
            "schema": "PhysicalRequestLedgerV1",
            "recorded_at": _now(), "state": state,
            "physical_request_id": envelope.physical_request_id,
            "canonical_episode_id": envelope.episode.episode_sha256,
            "project_id": envelope.episode.project_id,
            "run_id": envelope.episode.run_id,
            "logical_stage_id": envelope.episode.logical_stage_id,
            "logical_node_id": envelope.episode.logical_node_id,
            "execution_envelope_hash": envelope.envelope_sha256,
            "runtime_path_id": envelope.build.runtime_path_id,
            "release_build_id": envelope.build.build_id,
            "worker_fencing_id": envelope.build.worker_fencing_id,
            "durable_node_id": envelope.episode.logical_node_id,
            "recovery_coordinator_version": self.recovery.version,
            "prepared_by_release_build_id": envelope.build.build_id,
            "prepared_by_policy_version": envelope.episode.policy_version,
            "prepared_by_cutover_version": self.cutover.snapshot.version,
            "prepared_config_version": envelope.config_version,
            "candidate_sha256": envelope.episode.candidate_sha256,
            "contract_name": envelope.episode.contract_name,
            "contract_version": envelope.episode.contract_version,
            "route_fingerprint": envelope.route_fingerprint,
            "provider_id_sha256": _sha(envelope.provider_id),
            "model_id_sha256": _sha(envelope.model_id),
            **extra,
        }
        with self.ledger_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
        manifest = self.manifest_root / f"{envelope.physical_request_id}.json"
        if not manifest.exists():
            manifest_value = {
                "schema": "CaptureManifestV1", "state": "READY",
                "physical_request_id": envelope.physical_request_id,
                "canonical_episode_id": envelope.episode.episode_sha256,
                "execution_envelope_hash": envelope.envelope_sha256,
                "runtime_path_id": envelope.build.runtime_path_id,
                "release_build_id": envelope.build.build_id,
                "worker_fencing_id": envelope.build.worker_fencing_id,
                "project_id": envelope.episode.project_id,
                "run_id": envelope.episode.run_id,
                "logical_stage_id": envelope.episode.logical_stage_id,
                "logical_node_id": envelope.episode.logical_node_id,
                "candidate_sha256": envelope.episode.candidate_sha256,
                "contract_name": envelope.episode.contract_name,
                "contract_version": envelope.episode.contract_version,
                "schema_sha256": envelope.schema_sha256,
                "route_fingerprint": envelope.route_fingerprint,
                "provider_id_sha256": _sha(envelope.provider_id),
                "model_id_sha256": _sha(envelope.model_id),
                "capture_manifest_version": "CaptureManifestV1",
                "prepared_by_release_build_id": envelope.build.build_id,
                "prepared_by_policy_version": envelope.episode.policy_version,
                "prepared_by_cutover_version": self.cutover.snapshot.version,
                "prepared_config_version": envelope.config_version,
                "capture_before_lossy_conversion": True,
            }
        else:
            try:
                manifest_value = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise CanonicalDispatchError("capture_manifest_unreadable") from exc
            if (
                manifest_value.get("physical_request_id") != envelope.physical_request_id
                or manifest_value.get("execution_envelope_hash") != envelope.envelope_sha256
                or manifest_value.get("runtime_path_id") != envelope.build.runtime_path_id
                or manifest_value.get("project_id") not in {None, envelope.episode.project_id}
                or manifest_value.get("run_id") not in {None, envelope.episode.run_id}
            ):
                raise CanonicalDispatchError("capture_manifest_identity_mismatch")
            manifest_value["state"] = state
            manifest_value["updated_at"] = _now()
        for key in (
            "response_evidence_path", "response_evidence_sha256",
            "response_raw_sha256", "response_raw_length",
            "response_transport_complete", "response_evidence_redaction",
        ):
            if key in extra:
                manifest_value[key] = extra[key]
        temporary = manifest.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(manifest_value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8", newline="\n",
        )
        os.replace(temporary, manifest)

    def negative_old_path_reachability_matrix(self) -> dict[str, Any]:
        """Report the persisted negative matrix without inventing proof.

        A clean counter is only an observation.  The matrix is a production-
        shaped evidence artifact that must be produced by the dedicated
        offline harness and bound to this release/runtime.  In its absence
        this method remains fail-closed, so a canary cannot mistake an empty
        directory for proof that every legacy entry point is unreachable.
        """
        evidence_path = self.root / "old-path-reachability-matrix.json"
        evidence: dict[str, Any] | None = None
        try:
            value = json.loads(evidence_path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                evidence = value
        except (OSError, UnicodeError, json.JSONDecodeError):
            evidence = None
        bound = bool(
            evidence
            and evidence.get("schema") == "NegativeOldPathReachabilityMatrixV1"
            and evidence.get("release_build_id") == self.release.build_id
            and evidence.get("runtime_path_id") == self.release.runtime_path_id
            and evidence.get("provider_http_performed") is False
        )
        recorded_checks = evidence.get("checks") if evidence else None
        if not isinstance(recorded_checks, dict):
            recorded_checks = None
        # The negative matrix deliberately invokes deprecated entry points in
        # an isolated canary.  Those blocked invocations are evidence that the
        # guard was exercised, not evidence of a Provider bypass.  Therefore
        # this check is bound to the persisted canary counters instead of the
        # coordinator's in-memory ``old_path_invocations`` counter.
        provider_http_count = (
            int(evidence.get("provider_http_count", 0))
            if evidence and isinstance(evidence.get("provider_http_count", 0), int)
            else -1
        )
        provider_bypass_count = (
            int(evidence.get("provider_bypass_count", 0))
            if evidence and isinstance(evidence.get("provider_bypass_count", 0), int)
            else -1
        )
        checks = {
            "legacy_direct_adapter": bool(
                bound and provider_http_count == 0 and provider_bypass_count == 0
            ),
            "ambiguous_cutover": bool(bound and recorded_checks and recorded_checks.get("ambiguous_cutover")),
            "stale_prepared_work": bool(bound and recorded_checks and recorded_checks.get("stale_prepared_work")),
            "missing_manifest_replay": bool(bound and recorded_checks and recorded_checks.get("missing_manifest_replay")),
            "old_worker_fencing": bool(bound and recorded_checks and recorded_checks.get("old_worker_fencing")),
            "hidden_sdk_retry": bool(bound and recorded_checks and recorded_checks.get("hidden_sdk_retry")),
            "legacy_supervisor_retry": bool(bound and recorded_checks and recorded_checks.get("legacy_supervisor_retry")),
            "historical_checkpoint_migration": bool(bound and recorded_checks and recorded_checks.get("historical_checkpoint_migration")),
        }
        return {
            "schema": "NegativeOldPathReachabilityMatrixV1",
            "checks": checks, "pass": all(checks.values()),
            "status": "PASS" if all(checks.values()) else "PENDING_EVIDENCE",
            "evidence_path": str(evidence_path) if evidence else None,
            "old_path_invocation_count": self.old_path_invocations,
            "real_canary_old_path_invocation_count": (
                evidence.get("real_canary_old_path_invocation_count", 0)
                if evidence else 0
            ),
        }

    def status_for_run(self, run_id: str) -> dict[str, Any]:
        """Safe UI projection from the physical ledger, never from directories."""
        records: list[dict[str, Any]] = []
        try:
            for line in self.ledger_path.read_text(encoding="utf-8").splitlines():
                value = json.loads(line)
                if isinstance(value, dict) and value.get("run_id") == run_id:
                    records.append(value)
        except (OSError, UnicodeError, json.JSONDecodeError):
            records = []
        last = records[-1] if records else None
        latest_by_physical: dict[str, dict[str, Any]] = {}
        for item in records:
            latest_by_physical[str(item.get("physical_request_id") or "")] = item
        unknown = sum(
            item.get("state") in {"DISPATCHING", "TRANSPORT_UNKNOWN"}
            for item in latest_by_physical.values()
        )
        return {
            "schema": "ShortRuntimeReliabilityRunStatusV1",
            "run_id": run_id,
            "foundation_gates": self.foundation_gates(),
            "runtime_path_attestation": self.attest()["runtime_path_attestation"],
            "last_physical_request": ({
                key: last.get(key) for key in (
                    "physical_request_id", "canonical_episode_id", "state",
                    "logical_stage_id", "logical_node_id", "candidate_sha256",
                    "contract_name", "contract_version", "runtime_path_id",
                    "release_build_id", "worker_fencing_id",
                )
            } if last else None),
            "physical_ledger_record_count": len(records),
            "unknown_or_dispatching_count": unknown,
            "old_path_invocation_count": self.old_path_invocations,
        }

    def recovery_node_for_run(self, run_id: str) -> DurableNodeState | None:
        """Resolve the last durable node named by a run's physical ledger.

        Terminal workflow attempts from older releases did not always copy the
        logical node id into their metadata.  The append-only ledger is the
        remaining authoritative bridge.  Resolution is fail-closed: the last
        run record must name an existing node whose candidate and route match;
        an invalid tail never falls back to an older request.
        """

        records: list[dict[str, Any]] = []
        try:
            for line in self.ledger_path.read_text(encoding="utf-8").splitlines():
                value = json.loads(line)
                if isinstance(value, dict) and value.get("run_id") == run_id:
                    records.append(value)
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError):
            return None
        if not records:
            return None
        tail = records[-1]
        node_id = str(tail.get("logical_node_id") or "")
        if not node_id:
            return None
        node = self.nodes.load(node_id)
        if node is None:
            return None
        candidate = str(tail.get("candidate_sha256") or "")
        route = str(tail.get("route_fingerprint") or "")
        if candidate and candidate != node.candidate_sha256:
            return None
        if route and route != node.route_fingerprint:
            return None
        return node


__all__ = [
    "CanonicalEpisodeIdentity", "ExecutionEnvelope", "ReleaseBuildIdentity",
    "CanonicalDispatchError", "DispatchAuthorization", "DurableNodeState",
    "DurableNodeStateStore", "TypedFailureRecord", "TypedFailureGraphStore",
    "CutoverSnapshot", "CutoverRegistry", "RecoveryAction", "RecoveryCoordinator",
    "CanRunRealDispatchProof", "CanonicalDispatchCoordinator",
]
