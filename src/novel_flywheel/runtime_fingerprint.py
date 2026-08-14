"""Runtime build/config fingerprint collection and independent verification.

Collection is observational: it reads local files and existing database
descriptors only. It never resolves providers, credentials, routes, or models.
"""

from __future__ import annotations

import dataclasses
import json
import os
import tempfile
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
    build = _build_parent(collection, child_map)
    feature_flags = feature_flag_definition(db, project_id)
    routes = route_role_binding_definition(db)
    execution_config = _execution_config_parent(feature_flags, routes)
    execution = make_definition("RuntimeExecutionFingerprintV1", {
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
    children = tuple([*child_map.values(), feature_flags, routes])
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
