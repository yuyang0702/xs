"""Runtime build/config fingerprint collection and independent verification.

Collection is observational: it reads local files and existing database
descriptors only. It never resolves providers, credentials, routes, or models.
"""

from __future__ import annotations

import dataclasses
import json
import os
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from novel_flywheel.runtime_fingerprint_build import (
    BuildManifestCollection,
    FingerprintUnavailable,
    collect_build_manifests,
    domain_sha256,
    installed_dependency_definition,
    make_definition,
    python_runtime_definition,
    verify_definition,
)


STORE_VERSION = "runtime-fingerprint-definition-store-v1"
STORE_DIRECTORY = "runtime-fingerprints-v1"
FEATURE_FLAG_ENVIRONMENT_ALLOWLIST = (
    "NOVEL_CANONICAL_SHADOW_V1",
    "NOVEL_RELIABILITY_TRACE",
    "NOVEL_SHORT_CANONICAL_V2",
)
FEATURE_FLAG_DATABASE_ALLOWLIST = ("short_canonical_v2",)
PROJECT_METADATA_FLAG_ALLOWLIST = (
    "market_baseline_enabled",
    "optimized_local_review_enabled",
)


def _identifier_hash(kind: str, value: str | None) -> str | None:
    if value is None:
        return None
    return domain_sha256(f"novel-flywheel-runtime-identifier-v1:{kind}", value)


def _definition_ref(definition: Mapping[str, Any]) -> dict[str, str]:
    return {
        "schema": str(definition["schema"]),
        "definition_sha256": str(definition["definition_sha256"]),
    }


def _definition_category(schema: str) -> str:
    if schema == "RuntimeBuildFingerprintV1":
        return "builds"
    if schema == "RuntimeExecutionConfigFingerprintV1":
        return "execution-configs"
    if schema in {
        "RuntimeExecutionFingerprintV1", "RuntimeFingerprintRunBindingV1",
    }:
        return "executions"
    if "SourceManifest" in schema or "BuildInputManifest" in schema \
            or "InstalledRuntimeManifest" in schema:
        return "source-manifests"
    return "definitions"


class DefinitionStore:
    """Content-addressed store outside every project/business artifact tree."""

    def __init__(self, data_dir: Path) -> None:
        self.root = data_dir.resolve() / "runtime" / STORE_DIRECTORY

    def path_for(self, schema: str, definition_sha256: str) -> Path:
        if len(definition_sha256) != 64 or any(
            char not in "0123456789abcdef" for char in definition_sha256
        ):
            raise ValueError("invalid definition SHA-256")
        safe_schema = "".join(
            char for char in schema if char.isascii() and char.isalnum()
        )
        if not safe_schema or safe_schema != schema:
            raise ValueError("invalid definition schema")
        # The schema is already domain-separated into the digest. Keeping the
        # on-disk path shallow also avoids Windows MAX_PATH failures in deeply
        # nested temporary data directories.
        return self.root / _definition_category(schema) / f"{definition_sha256}.json"

    def write(self, definition: Mapping[str, Any]) -> Path:
        if not verify_definition(definition):
            raise ValueError("definition is not internally valid")
        schema = str(definition["schema"])
        digest = str(definition["definition_sha256"])
        target = self.path_for(schema, digest)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            existing = self.read(schema, digest)
            if existing != dict(definition):
                raise ValueError("content-addressed definition collision")
            return target
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{digest}.", suffix=".tmp", dir=target.parent,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(
                    definition, handle, ensure_ascii=False, sort_keys=True,
                    separators=(",", ":"), allow_nan=False,
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, target)
        finally:
            try:
                Path(temporary_name).unlink(missing_ok=True)
            except OSError:
                pass
        return target

    def read(self, schema: str, definition_sha256: str) -> dict[str, Any]:
        path = self.path_for(schema, definition_sha256)
        definition = json.loads(path.read_text(encoding="utf-8"))
        if not verify_definition(definition):
            raise ValueError("stored definition failed hash verification")
        if (
            definition["schema"] != schema
            or definition["definition_sha256"] != definition_sha256
        ):
            raise ValueError("stored definition identity mismatch")
        return definition

    def write_graph(
        self, parent: Mapping[str, Any], children: Iterable[Mapping[str, Any]],
    ) -> None:
        for child in children:
            self.write(child)
        self.write(parent)

    def verify_graph(self, parent: Mapping[str, Any]) -> dict[str, Any]:
        if not verify_definition(parent):
            return {"valid": False, "reason_codes": ["parent_definition_invalid"]}
        refs = parent.get("payload", {}).get("child_definitions", {})
        if not isinstance(refs, dict):
            return {"valid": False, "reason_codes": ["child_reference_map_invalid"]}
        reasons: list[str] = []
        for name, ref in sorted(refs.items()):
            if not isinstance(ref, dict):
                reasons.append(f"child_reference_invalid:{name}")
                continue
            try:
                self.read(str(ref["schema"]), str(ref["definition_sha256"]))
            except (KeyError, OSError, ValueError, json.JSONDecodeError):
                reasons.append(f"child_definition_invalid:{name}")
        return {"valid": not reasons, "reason_codes": reasons}


def contract_registry_definition() -> dict[str, Any]:
    from novel_flywheel.generated_artifacts import ARTIFACT_CONTRACT_REGISTRY

    return make_definition("RuntimeContractRegistryManifestV1", {
        "contracts": [
            registration.model_dump(mode="json")
            for _, registration in sorted(ARTIFACT_CONTRACT_REGISTRY.items())
        ],
    })


def adapter_manifest_definition() -> dict[str, Any]:
    from novel_flywheel.generated_artifacts import CONTRACT_ADAPTER_REGISTRY

    return make_definition("RuntimeAdapterManifestV1", {
        "adapters": [
            descriptor.model_dump(mode="json")
            for contract_name, descriptors in sorted(CONTRACT_ADAPTER_REGISTRY.items())
            for descriptor in sorted(descriptors, key=lambda item: item.name)
        ],
    })


def recovery_policy_definition() -> dict[str, Any]:
    from novel_flywheel.generated_artifacts import (
        ARTIFACT_CONTRACT_REGISTRY,
        EXECUTABLE_RECOVERY_STEP_OWNERS,
    )

    return make_definition("RuntimeRecoveryPolicyManifestV1", {
        "step_owners": [
            {"step": step, "owner": owner}
            for step, owner in sorted(EXECUTABLE_RECOVERY_STEP_OWNERS.items())
        ],
        "contract_ladders": [
            {"contract": name, "steps": list(registration.recovery_ladder)}
            for name, registration in sorted(ARTIFACT_CONTRACT_REGISTRY.items())
        ],
    })


def incident_catalog_definition() -> dict[str, Any]:
    from novel_flywheel.production_incidents import INCIDENT_DEFINITIONS

    return make_definition("RuntimeIncidentCatalogManifestV1", {
        "catalog_version": "production-incident-catalog-v1",
        "incidents": [dataclasses.asdict(item) for item in INCIDENT_DEFINITIONS],
    })


def feature_flag_definition(db: Any, project_id: str | None) -> dict[str, Any]:
    environment = [
        {
            "name": name,
            "status": "set" if name in os.environ else "defaulted",
            "enabled": os.environ.get(name, "0") == "1",
        }
        for name in FEATURE_FLAG_ENVIRONMENT_ALLOWLIST
    ]
    database_flags = []
    for name in FEATURE_FLAG_DATABASE_ALLOWLIST:
        value = db.feature_flag(name, project_id=project_id, default=False)
        database_flags.append({
            "name": name,
            "scope_type": value["scope_type"],
            "enabled": bool(value["enabled"]),
            "config_status": "present" if value.get("config") else "empty",
        })
    metadata_flags = []
    project = db.get_project(project_id) if project_id else None
    metadata = (project or {}).get("metadata") or {}
    for name in PROJECT_METADATA_FLAG_ALLOWLIST:
        metadata_flags.append({
            "name": name,
            "status": "set" if name in metadata else "unavailable",
            "enabled": bool(metadata[name]) if name in metadata else None,
        })
    return make_definition("RuntimeFeatureFlagManifestV1", {
        "environment": environment,
        "database": database_flags,
        "project_metadata": metadata_flags,
    })


def route_role_binding_definition(db: Any) -> dict[str, Any]:
    providers: list[dict[str, Any]] = []
    models: list[dict[str, Any]] = []
    for provider in db.list_providers():
        provider_id = str(provider["id"])
        providers.append({
            "provider_id_hash": _identifier_hash("provider", provider_id),
            "protocol": str(provider.get("protocol") or "unknown"),
            "auth_type": str(provider.get("auth_type") or "unknown"),
            "enabled": bool(provider.get("enabled")),
            "timeout_seconds": int(provider.get("timeout_seconds") or 0),
            "endpoint_status": "configured" if provider.get("base_url") else "unavailable",
            "extra_header_names_sha256": domain_sha256(
                "novel-flywheel-header-name-set-v1",
                sorted(str(name).casefold() for name in provider.get("extra_headers", {})),
            ),
        })
        for model in db.list_models(provider_id):
            models.append({
                "model_id_hash": _identifier_hash("model", str(model["id"])),
                "provider_id_hash": _identifier_hash("provider", provider_id),
                "model_name_hash": _identifier_hash(
                    "model-name", str(model.get("model_name") or ""),
                ),
                "context_window": model.get("context_window"),
                "max_output_tokens": model.get("max_output_tokens"),
                "capabilities": model.get("capabilities") or {},
            })
    bindings = [{
        "role": str(binding["role"]),
        "primary_provider_id_hash": _identifier_hash(
            "provider", str(binding["primary_provider_id"]),
        ),
        "primary_model_id_hash": _identifier_hash(
            "model", str(binding["primary_model_id"]),
        ),
        "fallback_provider_id_hash": _identifier_hash(
            "provider", binding.get("fallback_provider_id"),
        ),
        "fallback_model_id_hash": _identifier_hash(
            "model", binding.get("fallback_model_id"),
        ),
    } for binding in db.list_role_bindings()]
    return make_definition("RuntimeRouteRoleBindingManifestV1", {
        "providers": providers,
        "models": models,
        "role_bindings": bindings,
        "credential_material_included": False,
    })


def _build_parent(
    collection: BuildManifestCollection,
    child_definitions: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    refs = {
        name: _definition_ref(definition)
        for name, definition in sorted(child_definitions.items())
    }
    content_refs = {
        name: ref for name, ref in refs.items() if name != "git_provenance"
    }
    content_hash = domain_sha256(
        "novel-flywheel-runtime-build-content-v1", content_refs,
    )
    return make_definition("RuntimeBuildFingerprintV1", {
        "mode": collection.mode,
        "runtime_build_status": collection.status,
        "build_fingerprint_sha256": content_hash,
        "child_definitions": refs,
        "reason_codes": list(collection.reason_codes),
        "human_summary": {
            "mode": collection.mode,
            "status": collection.status,
            "contract_count": len(
                child_definitions["contract_registry"]["payload"]["contracts"]
            ),
            "adapter_count": len(
                child_definitions["adapter_manifest"]["payload"]["adapters"]
            ),
            "incident_family_count": len(
                child_definitions["incident_catalog"]["payload"]["incidents"]
            ),
            "credential_material_included": False,
        },
    })


def _execution_config_parent(
    feature_flags: Mapping[str, Any], routes: Mapping[str, Any],
) -> dict[str, Any]:
    refs = {
        "feature_flags": _definition_ref(feature_flags),
        "route_role_bindings": _definition_ref(routes),
    }
    return make_definition("RuntimeExecutionConfigFingerprintV1", {
        "execution_config_fingerprint_sha256": domain_sha256(
            "novel-flywheel-runtime-execution-config-v1", refs,
        ),
        "child_definitions": refs,
        "human_summary": {
            "role_binding_count": len(routes["payload"]["role_bindings"]),
            "provider_descriptor_count": len(routes["payload"]["providers"]),
            "enabled_flags": sorted(
                item["name"] for group in (
                    feature_flags["payload"]["environment"],
                    feature_flags["payload"]["database"],
                    feature_flags["payload"]["project_metadata"],
                )
                for item in group if item.get("enabled") is True
            ),
            "credential_material_included": False,
        },
    })


def collect_build_fingerprint(
    *, module_file: Path | None = None,
) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]:
    collection = collect_build_manifests(module_file=module_file)
    child_map: dict[str, dict[str, Any]] = {
        "contract_registry": contract_registry_definition(),
        "adapter_manifest": adapter_manifest_definition(),
        "recovery_policy": recovery_policy_definition(),
        "incident_catalog": incident_catalog_definition(),
        "python_runtime": python_runtime_definition(),
        "installed_dependencies": installed_dependency_definition(),
    }
    optional = {
        "build_input": collection.build_input,
        "installed_runtime": collection.installed_runtime,
        "production_source": collection.production_source,
        "git_provenance": collection.provenance,
    }
    child_map.update({name: item for name, item in optional.items() if item is not None})
    return _build_parent(collection, child_map), tuple(child_map.values())


def collect_execution_config_fingerprint(
    db: Any, *, project_id: str | None = None,
) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]:
    feature_flags = feature_flag_definition(db, project_id)
    routes = route_role_binding_definition(db)
    return _execution_config_parent(feature_flags, routes), (feature_flags, routes)


def combine_runtime_execution_fingerprint(
    build: Mapping[str, Any], execution_config: Mapping[str, Any],
) -> dict[str, Any]:
    return make_definition("RuntimeExecutionFingerprintV1", {
        "build_fingerprint_sha256": build["payload"]["build_fingerprint_sha256"],
        "execution_config_fingerprint_sha256": (
            execution_config["payload"]["execution_config_fingerprint_sha256"]
        ),
        "execution_fingerprint_sha256": domain_sha256(
            "novel-flywheel-runtime-execution-v1", {
                "build": build["payload"]["build_fingerprint_sha256"],
                "execution_config": execution_config["payload"][
                    "execution_config_fingerprint_sha256"
                ],
            },
        ),
        "child_definitions": {
            "build": _definition_ref(build),
            "execution_config": _definition_ref(execution_config),
        },
    })


@dataclass(frozen=True)
class RuntimeFingerprintSnapshotV1:
    build: dict[str, Any]
    execution_config: dict[str, Any]
    execution: dict[str, Any]
    children: tuple[dict[str, Any], ...]

    @property
    def build_fingerprint_sha256(self) -> str:
        return str(self.build["payload"]["build_fingerprint_sha256"])

    @property
    def execution_config_fingerprint_sha256(self) -> str:
        return str(
            self.execution_config["payload"]["execution_config_fingerprint_sha256"]
        )

    @property
    def execution_fingerprint_sha256(self) -> str:
        return str(self.execution["payload"]["execution_fingerprint_sha256"])


def collect_runtime_fingerprint(
    db: Any, *, project_id: str | None = None,
    module_file: Path | None = None,
) -> RuntimeFingerprintSnapshotV1:
    build, build_children = collect_build_fingerprint(module_file=module_file)
    execution_config, config_children = collect_execution_config_fingerprint(
        db, project_id=project_id,
    )
    execution = combine_runtime_execution_fingerprint(build, execution_config)
    children = (*build_children, *config_children)
    return RuntimeFingerprintSnapshotV1(
        build=build, execution_config=execution_config,
        execution=execution, children=children,
    )


def persist_runtime_fingerprint(
    store: DefinitionStore, snapshot: RuntimeFingerprintSnapshotV1,
) -> None:
    store.write_graph(snapshot.build, snapshot.children)
    store.write_graph(snapshot.execution_config, snapshot.children)
    store.write(snapshot.execution)


def compare_runtime_fingerprints(
    origin: RuntimeFingerprintSnapshotV1, current: RuntimeFingerprintSnapshotV1,
) -> dict[str, Any]:
    build_changed = origin.build_fingerprint_sha256 != current.build_fingerprint_sha256
    config_changed = (
        origin.execution_config_fingerprint_sha256
        != current.execution_config_fingerprint_sha256
    )
    provenance_changed = (
        origin.build["payload"]["child_definitions"].get("git_provenance")
        != current.build["payload"]["child_definitions"].get("git_provenance")
    )
    return {
        "comparison_status": "exact" if not (build_changed or config_changed) else "changed",
        "runtime_changed_during_run": build_changed or config_changed,
        "build_changed_during_run": build_changed,
        "execution_config_changed_during_run": config_changed,
        "provenance_changed_only": (
            provenance_changed and not build_changed and not config_changed
        ),
    }


_PROCESS_BUILD_LOCK = threading.Lock()
_PROCESS_BUILD: tuple[dict[str, Any], tuple[dict[str, Any], ...]] | None = None


def process_captured_build_fingerprint() -> tuple[
    dict[str, Any], tuple[dict[str, Any], ...]
]:
    """Capture build identity once per process, as required for run lineage."""

    global _PROCESS_BUILD
    with _PROCESS_BUILD_LOCK:
        if _PROCESS_BUILD is None:
            _PROCESS_BUILD = collect_build_fingerprint()
        return _PROCESS_BUILD


def _binding_event_metadata(event: Mapping[str, Any]) -> dict[str, Any] | None:
    if event.get("event_type") != "runtime_fingerprint_binding_v1":
        return None
    metadata = event.get("metadata")
    return metadata if isinstance(metadata, dict) else None


def canonical_runtime_bindings(db: Any, run_id: str) -> dict[str, Any]:
    """Deduplicate exact bindings and preserve contradictory epochs."""

    logical: dict[str, dict[str, Any]] = {}
    epoch_fingerprints: dict[tuple[str, str], set[str]] = {}
    for event in db.list_run_events(run_id):
        metadata = _binding_event_metadata(event)
        if metadata is None:
            continue
        definition_sha256 = str(metadata.get("binding_definition_sha256") or "")
        if len(definition_sha256) != 64:
            continue
        logical.setdefault(definition_sha256, metadata)
        key = (
            str(metadata.get("binding_kind") or "unknown"),
            str(metadata.get("execution_epoch") or "unknown"),
        )
        epoch_fingerprints.setdefault(key, set()).add(
            str(metadata.get("runtime_execution_fingerprint") or "unknown")
        )
    bindings = sorted(
        logical.values(),
        key=lambda item: (
            str(item.get("binding_kind")), str(item.get("execution_epoch")),
            str(item.get("binding_definition_sha256")),
        ),
    )
    conflicts = [
        {
            "binding_kind": kind,
            "execution_epoch": epoch,
            "runtime_execution_fingerprints": sorted(fingerprints),
        }
        for (kind, epoch), fingerprints in sorted(epoch_fingerprints.items())
        if len(fingerprints) > 1
    ]
    origins = [item for item in bindings if item.get("binding_kind") == "origin"]
    return {
        "bindings": bindings,
        "logical_binding_count": len(bindings),
        "origin_count": len(origins),
        "origin_runtime_execution_fingerprint": (
            origins[0].get("runtime_execution_fingerprint")
            if len(origins) == 1 else None
        ),
        "binding_status": (
            "conflict" if conflicts or len(origins) > 1
            else "exact" if len(origins) == 1
            else "unverifiable_legacy"
        ),
        "conflicts": conflicts,
    }


class RuntimeFingerprintRecorderV1:
    """Best-effort post-commit run lineage recorder."""

    def __init__(
        self, db: Any, data_dir: Path, *,
        process_build: dict[str, Any] | None = None,
        build_children: tuple[dict[str, Any], ...] | None = None,
    ) -> None:
        self.db = db
        self.store = DefinitionStore(data_dir)
        if process_build is None or build_children is None:
            process_build, build_children = process_captured_build_fingerprint()
        self.process_build = process_build
        self.build_children = build_children
        self.store.write_graph(self.process_build, self.build_children)

    def __call__(self, observation: Mapping[str, Any]) -> None:
        try:
            self._record(observation)
        except Exception as exc:
            self._record_unavailable(observation, exc)

    def _record(self, observation: Mapping[str, Any]) -> None:
        run_id = str(observation["run_id"])
        project_id = str(observation["project_id"])
        kind = str(observation["binding_kind"])
        epoch = str(observation["execution_epoch"])
        if kind not in {"origin", "executor"}:
            raise ValueError("unsupported runtime binding kind")
        execution_config, config_children = collect_execution_config_fingerprint(
            self.db, project_id=project_id,
        )
        execution = combine_runtime_execution_fingerprint(
            self.process_build, execution_config,
        )
        self.store.write_graph(execution_config, config_children)
        self.store.write(execution)
        current = canonical_runtime_bindings(self.db, run_id)
        origin_fingerprint = current["origin_runtime_execution_fingerprint"]
        binding_status = "exact"
        if kind == "executor" and origin_fingerprint is None:
            binding_status = "unverifiable_legacy"
        binding = make_definition("RuntimeFingerprintRunBindingV1", {
            "run_id_hash": _identifier_hash("run", run_id),
            "project_id_hash": _identifier_hash("project", project_id),
            "workflow": str(observation.get("workflow") or "unknown"),
            "binding_kind": kind,
            "execution_epoch": epoch,
            "binding_status": binding_status,
            "runtime_execution_fingerprint": execution["payload"][
                "execution_fingerprint_sha256"
            ],
            "runtime_execution_definition": _definition_ref(execution),
            "build_fingerprint_sha256": self.process_build["payload"][
                "build_fingerprint_sha256"
            ],
            "execution_config_fingerprint_sha256": execution_config["payload"][
                "execution_config_fingerprint_sha256"
            ],
            "origin_runtime_execution_fingerprint": (
                execution["payload"]["execution_fingerprint_sha256"]
                if kind == "origin" else origin_fingerprint
            ),
            "process_captured": True,
        })
        self.store.write(binding)
        metadata = {
            **binding["payload"],
            "binding_definition_sha256": binding["definition_sha256"],
        }
        if any(
            item.get("binding_definition_sha256") == binding["definition_sha256"]
            for item in current["bindings"]
        ):
            return
        self.db.add_run_event(
            run_id, "info", "runtime_fingerprint_binding_v1",
            "Runtime identity observed", stage="runtime_identity",
            metadata=metadata,
        )

    def _record_unavailable(
        self, observation: Mapping[str, Any], exc: Exception,
    ) -> None:
        try:
            self.db.add_run_event(
                str(observation["run_id"]), "warning",
                "runtime_fingerprint_unavailable_v1",
                "Runtime identity observation unavailable",
                stage="runtime_identity", metadata={
                    "binding_kind": observation.get("binding_kind"),
                    "execution_epoch": observation.get("execution_epoch"),
                    "runtime_build_status": "unknown_runtime",
                    "reason_code": (
                        exc.reason_code if isinstance(exc, FingerprintUnavailable)
                        else "runtime_fingerprint_observer_failed"
                    ),
                },
            )
        except Exception:
            # A double failure is a coverage gap. It must never affect business.
            return


def _children_by_reference(
    children: Iterable[Mapping[str, Any]],
) -> dict[tuple[str, str], Mapping[str, Any]]:
    return {
        (str(item["schema"]), str(item["definition_sha256"])): item
        for item in children
    }


def runtime_source_revalidation(
    process_build: Mapping[str, Any], current_build: Mapping[str, Any], *,
    process_children: Iterable[Mapping[str, Any]],
    current_children: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Compare actual current manifests to process-start manifests, no mtime."""

    process_index = _children_by_reference(process_children)
    current_index = _children_by_reference(current_children)
    process_refs = process_build["payload"]["child_definitions"]
    current_refs = current_build["payload"]["child_definitions"]

    def definition_for(
        refs: Mapping[str, Any], index: Mapping[tuple[str, str], Mapping[str, Any]],
        name: str,
    ) -> Mapping[str, Any] | None:
        ref = refs.get(name)
        if not isinstance(ref, dict):
            return None
        return index.get((str(ref.get("schema")), str(ref.get("definition_sha256"))))

    mode = str(current_build["payload"].get("mode") or "unknown")
    source_name = "production_source" if mode == "git_workspace" else "installed_runtime"
    process_source_ref = process_refs.get(source_name)
    current_source_ref = current_refs.get(source_name)
    source_changed = process_source_ref != current_source_ref
    build_changed = (
        process_build["payload"].get("build_fingerprint_sha256")
        != current_build["payload"].get("build_fingerprint_sha256")
    )
    process_provenance = process_refs.get("git_provenance")
    current_provenance = current_refs.get("git_provenance")
    provenance_changed = process_provenance != current_provenance
    current_git = definition_for(current_refs, current_index, "git_provenance")
    production_source_clean = None
    if current_git is not None:
        production_source_clean = not bool(
            current_git["payload"].get("production_source_dirty")
        )
    current_source = definition_for(current_refs, current_index, source_name)
    process_source = definition_for(process_refs, process_index, source_name)
    comparable = current_source is not None and process_source is not None
    status = str(current_build["payload"].get("runtime_build_status") or "unknown_runtime")
    exact = comparable and not build_changed and not source_changed and status in {
        "verified_git_workspace", "verified_packaged_manifest",
    }
    return {
        "deployment_mode": mode,
        "comparison_status": "exact" if exact else "changed" if comparable else "unknown",
        "runtime_build_status": status if exact else "runtime_not_exact",
        "source_changed_after_process_start": bool(source_changed),
        "build_changed_after_process_start": bool(build_changed),
        "provenance_changed_only": bool(
            provenance_changed and not build_changed and not source_changed
        ),
        "production_source_clean": production_source_clean,
        "installed_manifest_exact": (
            exact if mode == "packaged" else None
        ),
        "embedded_manifest_exact": (
            status == "verified_packaged_manifest" if mode == "packaged" else None
        ),
    }


def verify_runtime_binding_sidecars(
    store: DefinitionStore, binding_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Independently re-hash binding, execution, build, config, and children."""

    reasons: list[str] = []
    try:
        binding = store.read(
            "RuntimeFingerprintRunBindingV1",
            str(binding_metadata["binding_definition_sha256"]),
        )
        for field in (
            "binding_kind", "execution_epoch", "runtime_execution_fingerprint",
            "build_fingerprint_sha256", "execution_config_fingerprint_sha256",
        ):
            if binding["payload"].get(field) != binding_metadata.get(field):
                reasons.append(f"binding_event_mismatch:{field}")
        execution_ref = binding["payload"]["runtime_execution_definition"]
        execution = store.read(
            str(execution_ref["schema"]), str(execution_ref["definition_sha256"]),
        )
        graph = store.verify_graph(execution)
        reasons.extend(graph["reason_codes"])
        for name, ref in execution["payload"]["child_definitions"].items():
            parent = store.read(str(ref["schema"]), str(ref["definition_sha256"]))
            nested = store.verify_graph(parent)
            reasons.extend(f"{name}:{code}" for code in nested["reason_codes"])
    except (KeyError, OSError, ValueError, json.JSONDecodeError):
        reasons.append("binding_sidecar_unavailable_or_invalid")
    return {
        "valid": not reasons,
        "validation_status": "exact" if not reasons else "invalid",
        "reason_codes": sorted(set(reasons)),
    }


@dataclass(frozen=True)
class CanaryRuntimeFingerprintPreflightV1:
    eligible: bool
    deployment_mode: str
    blocked_reason_codes: tuple[str, ...]
    validation_receipt_sha256: str


def canary_runtime_fingerprint_preflight_v1(
    *, deployment_mode: str,
    approved_build_fingerprint: str | None,
    approved_execution_config_fingerprint: str | None,
    origin_binding: Mapping[str, Any] | None,
    executor_binding: Mapping[str, Any] | None,
    current_source_revalidation: Mapping[str, Any],
    sidecar_validation: Mapping[str, Any],
    contradictory_binding: bool = False,
) -> CanaryRuntimeFingerprintPreflightV1:
    """Pure future-canary eligibility verifier; it has no I/O or side effects."""

    reasons: list[str] = []
    if deployment_mode not in {"git_workspace", "packaged"}:
        reasons.append("deployment_mode_unknown")
    if not approved_build_fingerprint:
        reasons.append("approved_build_missing")
    if not approved_execution_config_fingerprint:
        reasons.append("approved_execution_config_missing")
    if origin_binding is None:
        reasons.append("origin_binding_missing")
    elif origin_binding.get("binding_status") != "exact":
        reasons.append("origin_binding_not_exact")
    if executor_binding is None:
        reasons.append("executor_binding_missing")
    elif executor_binding.get("binding_status") != "exact":
        reasons.append("executor_binding_not_exact")
    if contradictory_binding:
        reasons.append("contradictory_binding")
    if executor_binding is not None:
        if executor_binding.get("build_fingerprint_sha256") != approved_build_fingerprint:
            reasons.append("build_fingerprint_unapproved")
        if (
            executor_binding.get("execution_config_fingerprint_sha256")
            != approved_execution_config_fingerprint
        ):
            reasons.append("execution_config_fingerprint_unapproved")
    if origin_binding is not None and executor_binding is not None and (
        executor_binding.get("origin_runtime_execution_fingerprint")
        != origin_binding.get("runtime_execution_fingerprint")
    ):
        reasons.append("origin_executor_binding_mismatch")
    if sidecar_validation.get("valid") is not True:
        reasons.append("sidecar_definition_not_exact")
    if current_source_revalidation.get("source_changed_after_process_start") is True:
        reasons.append("source_changed_after_process_start")
    if current_source_revalidation.get("comparison_status") != "exact":
        reasons.append("current_runtime_not_exact")
    if deployment_mode == "git_workspace":
        if current_source_revalidation.get("runtime_build_status") != "verified_git_workspace":
            reasons.append("git_workspace_not_verified")
        if current_source_revalidation.get("production_source_clean") is not True:
            reasons.append("production_source_not_clean")
    if deployment_mode == "packaged":
        if current_source_revalidation.get("runtime_build_status") != "verified_packaged_manifest":
            reasons.append("packaged_manifest_not_verified")
        if current_source_revalidation.get("installed_manifest_exact") is not True:
            reasons.append("installed_manifest_not_exact")
        if current_source_revalidation.get("embedded_manifest_exact") is not True:
            reasons.append("embedded_manifest_not_exact")
    blocked = tuple(sorted(set(reasons)))
    receipt_payload = {
        "schema": "CanaryRuntimeFingerprintPreflightV1",
        "deployment_mode": deployment_mode,
        "eligible": not blocked,
        "blocked_reason_codes": list(blocked),
        "approved_build_fingerprint": approved_build_fingerprint,
        "approved_execution_config_fingerprint": approved_execution_config_fingerprint,
        "origin_binding_definition_sha256": (
            origin_binding or {}
        ).get("binding_definition_sha256"),
        "executor_binding_definition_sha256": (
            executor_binding or {}
        ).get("binding_definition_sha256"),
        "source_comparison_status": current_source_revalidation.get(
            "comparison_status"
        ),
        "sidecar_validation_status": sidecar_validation.get("validation_status"),
    }
    return CanaryRuntimeFingerprintPreflightV1(
        eligible=not blocked, deployment_mode=deployment_mode,
        blocked_reason_codes=blocked,
        validation_receipt_sha256=domain_sha256(
            "novel-flywheel-canary-runtime-preflight-v1", receipt_payload,
        ),
    )
