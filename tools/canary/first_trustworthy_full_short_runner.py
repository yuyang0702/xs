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
from typing import Any, Callable
from urllib.parse import urlsplit

from novel_flywheel.config import Settings, configure_runtime_environment
from novel_flywheel.db import Database
from novel_flywheel.full_short_execution import (
    FullShortDispatchLedgerObserverV1,
    FullShortDurableExecutionStoreV1,
    build_full_short_completion_receipt_v1,
    validate_full_short_canonical_authorization_v1,
    validate_full_short_preflight_v1,
)
from novel_flywheel.models import ModelGateway
from novel_flywheel.nlp_backend import LocalNLPManager
from novel_flywheel.projects import ProjectStore
from novel_flywheel.providers.http import SingleDispatchTransportPolicyV1
from novel_flywheel.providers.registry import ProviderRegistry
from novel_flywheel.prompts import OPTIONAL_PROMPT_SKILLS, REQUIRED_SKILLS
from novel_flywheel.quality_profiles import profile_for_project
from novel_flywheel.reference_library import ReferenceLibrary
from novel_flywheel.runtime_fingerprint import collect_runtime_fingerprint_v2
from novel_flywheel.secrets import KeyringSecretStore
from novel_flywheel.short_canonical_promotion import (
    short_canonical_feature_snapshot,
)
from novel_flywheel.skills import SkillGate, SkillScanner
from novel_flywheel.skill_prompts import (
    ConstraintPromptCompactor,
    SkillPromptCompactor,
)
from novel_flywheel.story_state import StoryStateStore
from novel_flywheel.style_context import selected_style_reference_provenance
from novel_flywheel.tasks import RunTaskManager
from novel_flywheel.workflows import WorkflowService
from tools.canary.short_completion import COMPLETION_GOAL
from tools.canary.short_completion_verification import verify_short_completion_v1


FULL_SHORT_BOUND_ROLES = (
    "planning", "draft", "review", "reader_review", "polish",
    "final_review", "maintenance", "revision_plan",
)
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


def collect_live_bindings(
    *, repo: Path, data_dir: Path, project_id: str, run_id: str,
    store_root: Path | None = None,
) -> tuple[dict, dict]:
    """Collect public, credential-free live bindings from source truth."""

    repo = repo.resolve(strict=True)
    data_dir = data_dir.resolve(strict=True)
    exact_store_root = _canonical_store_root(
        repo=repo, data_dir=data_dir, store_root=store_root,
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
    for role in FULL_SHORT_BOUND_ROLES:
        binding = db.get_role_binding(role) or {}
        if role in FULL_SHORT_REQUIRED_EXECUTION_ROLES and not (
            binding.get("primary_provider_id")
            and binding.get("primary_model_id")
        ):
            raise ValueError("required Full Short primary route is missing")
        for lane in ("primary", "fallback"):
            provider_id = binding.get(f"{lane}_provider_id")
            model_id = binding.get(f"{lane}_model_id")
            if not provider_id or not model_id:
                continue
            provider = db.get_provider(str(provider_id))
            model = db.get_model(str(model_id))
            if not provider or not model or not provider.get("enabled"):
                raise ValueError("route binding is incomplete or disabled")
            destination = _destination(provider)
            destinations.add(destination)
            configured_max = model.get("max_output_tokens")
            stage_budget_role = "review" if role == "reader_review" else role
            max_output = int(
                configured_max
                or WorkflowService._stage_output_budget(stage_budget_role)
            )
            if max_output <= 0:
                raise ValueError("runtime stage output cap is unavailable")
            max_per_call = max(max_per_call, max_output)
            records.append({
                "role": role, "lane": lane,
                "provider_id_sha256": hashlib.sha256(
                    str(provider_id).encode("utf-8"),
                ).hexdigest(),
                "provider_name": str(provider.get("name") or ""),
                "model_id_sha256": hashlib.sha256(
                    str(model_id).encode("utf-8"),
                ).hexdigest(),
                "model_name": str(model.get("model_name") or ""),
                "protocol": str(provider["protocol"]),
                "route_fingerprint": ProviderRegistry.route_fingerprint(
                    provider, model,
                ),
                "destination": destination,
                "max_output_tokens": max_output,
                "max_output_token_source": (
                    "model_configuration" if configured_max
                    else "runtime_stage_policy"
                ),
            })
    records.sort(key=lambda item: (item["role"], item["lane"]))
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
    actual = {
        "head": _git(repo, "rev-parse", "HEAD"),
        "branch": _git(repo, "branch", "--show-current"),
        "run_id": run_id,
        "worktree_clean": _git(repo, "status", "--porcelain") == "",
        "project_id_sha256": hashlib.sha256(project_id.encode()).hexdigest(),
        "workload_sha256": _domain(workload),
        "runtime_authority_sha256": _domain(runtime),
        "style_reference_authority_sha256": _domain(style),
        "route_manifest_sha256": route_manifest_sha256,
        "destination_manifest_sha256": destination_manifest_sha256,
        "egress_policy_sha256": _domain(egress),
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
        "routes": records,
        "destinations": sorted(destinations),
        "destination_operators": [{
            "destination": destination,
            "operator_classification": "THIRD_PARTY_ENDPOINT_LOCAL_METADATA_ONLY",
        } for destination in sorted(destinations)],
        "egress_policy": egress,
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
        raise ValueError("FULL_SHORT_MONETARY_COST_STATE_NOT_EXACT")
    actual, live_public = collect_live_bindings(
        repo=args.repo, data_dir=args.data_dir,
        project_id=str(bindings["project_id"]),
        run_id=str(policy["run_id"]), store_root=args.store_root,
    )
    if live_public != bindings:
        raise ValueError("PUBLIC_BINDINGS_DRIFT")
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
        raise RuntimeError("FULL_SHORT_LEDGER_CREATED_AT_INVALID") from exc
    elapsed = max(
        0,
        int((datetime.now(timezone.utc) - created_at).total_seconds()),
    )
    if elapsed > int(policy["maximum_elapsed_seconds"]):
        raise RuntimeError("FULL_SHORT_MAXIMUM_ELAPSED_EXPIRED_AT_COMPLETION")
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
    if (
        "http_transport_factory" in signature.parameters
        or any(
            item.kind is inspect.Parameter.VAR_KEYWORD
            for item in signature.parameters.values()
        )
    ):
        kwargs["http_transport_factory"] = http_transport_factory
    return factory(db, secret_store, **kwargs)


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
            raise RuntimeError("FULL_SHORT_EXACT_RESERVATION_API_UNAVAILABLE")
        manager.start_exact_once(
            execution_id, project_id, "short-story", operation,
            terminal_finalizer=terminal_finalizer,
        )
    task = manager.tasks.get(execution_id)
    if task is None:
        raise RuntimeError("FULL_SHORT_RESERVED_TASK_NOT_LAUNCHED")
    await task


def _full_short_runtime_components(
    *, repo: Path, data_dir: Path, project_id: str, execution_id: str,
    registry: ProviderRegistry, manager: RunTaskManager | None = None,
) -> tuple[Database, Any, WorkflowService, RunTaskManager]:
    """Build the exact production task-manager and WorkflowService assembly."""

    settings = Settings(data_dir.resolve(strict=True))
    configure_runtime_environment(settings.data_dir)
    db = Database(settings.database_path)
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


async def execute_full_short_control_plane(
    args: argparse.Namespace,
    authorization: dict[str, Any],
    *,
    external_actions_enabled: bool,
    secret_store_factory: Callable[[], Any],
    registry_factory: Callable[..., ProviderRegistry] | None = None,
    http_transport_factory: Callable[..., Any] | None = None,
    required_stage_roles: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Execute the real control-plane, task manager, and WorkflowService path.

    Production supplies no factories and therefore uses the keyring plus the
    real provider transport.  An offline replay may replace only the secret
    store and the registry's lowest HTTP transport.
    """

    raw = _authorization_raw(args)
    raw_sha256 = hashlib.sha256(raw).hexdigest()
    if raw_sha256 != args.activated_sha256:
        raise ValueError("ACTIVATED_AUTHORIZATION_SHA256_MISMATCH")
    live_authorization, _preflight = preflight_full_short_control_plane(
        args, raw, external_actions_enabled=external_actions_enabled,
    )
    if live_authorization != authorization:
        raise ValueError("FULL_SHORT_AUTHORIZATION_OBJECT_DRIFT")
    policy = authorization["policy"]
    bindings = authorization["public_bindings"]
    settings = Settings(args.data_dir.resolve(strict=True))
    configure_runtime_environment(settings.data_dir)
    db = Database(settings.database_path)
    execution_id = policy["run_id"]
    manager = RunTaskManager(db)
    manager.reserve_exact_once(
        execution_id, str(bindings["project_id"]), "short-story",
    )
    store = FullShortDurableExecutionStoreV1(
        repo_root=args.repo, store_root=args.store_root,
    )
    permission = store.create_permission(
        execution_id=execution_id,
        authorization_text_sha256=args.activated_sha256,
        policy=policy, external_actions_enabled=external_actions_enabled,
    )
    approval = store.create_jit_approval(
        execution_id=execution_id, policy=policy, permission=permission,
        external_actions_enabled=external_actions_enabled,
    )
    nonce = store.reserve_nonce(
        execution_id=execution_id, policy=policy, approval=approval,
        external_actions_enabled=external_actions_enabled,
    )
    observer = FullShortDispatchLedgerObserverV1(
        store=store, execution_id=execution_id, policy=policy,
        authorized_routes=tuple(bindings["routes"]),
        egress_policy=bindings["egress_policy"],
        external_actions_enabled=external_actions_enabled,
    )
    registry = _registry_from_factory(
        registry_factory, db=db, secret_store=secret_store_factory(),
        observer=observer, http_transport_factory=http_transport_factory,
    )
    db, project, service, manager = _full_short_runtime_components(
        repo=args.repo, data_dir=settings.data_dir,
        project_id=str(bindings["project_id"]), execution_id=execution_id,
        registry=registry, manager=manager,
    )
    closure_state: dict[str, Any] = {}

    def terminal_closure(
        actual_run_id: str, _operation_result: object,
        live_authority: dict[str, object],
    ) -> Callable[[], dict[str, Any]]:
        if actual_run_id != execution_id:
            raise RuntimeError("FULL_SHORT_TERMINAL_RUN_ID_DRIFT")
        ledger = store.load_ledger(execution_id)
        completed_stage_receipts = ledger.get("completed_stage_receipts")
        if not isinstance(completed_stage_receipts, list):
            raise RuntimeError("FULL_SHORT_STAGE_RECEIPTS_NOT_AVAILABLE")
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
            raise RuntimeError("FULL_SHORT_REQUIRED_STAGE_ROLE_NOT_EXECUTED")
        run_root = Path(str(live_authority["run_root"]))
        project_root = Path(str(live_authority["project_root"]))
        terminal = verify_short_completion_v1(
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
        )
        closure_state["terminal"] = terminal
        if terminal.get("completion_goal_outcome") != COMPLETION_GOAL:
            raise RuntimeError("FULL_SHORT_TERMINAL_VERIFICATION_NOT_EXACT")
        try:
            elapsed_seconds = _completion_elapsed_recheck(policy, ledger)
            receipt = build_full_short_completion_receipt_v1(
                execution_id=execution_id, policy=policy,
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
            )
        except Exception as exc:
            closure_state["terminal_failure"] = {
                "exception_type": type(exc).__name__,
                "safe_code": str(exc)[:240],
            }
            raise
        closure_state.update({
            "terminal": terminal, "ledger": ledger,
            "elapsed_seconds": elapsed_seconds,
            "observed_roles": list(observed_roles),
            "receipt": receipt,
        })

        def commit_after_saga_cleanup() -> dict[str, Any]:
            completion = store.commit_completion(
                execution_id=execution_id, receipt=receipt,
            )
            closure_state["completion"] = completion
            return completion

        return commit_after_saga_cleanup

    terminal_finalizer = service.bind_full_short_terminal_finalizer(
        execution_id, project.id, terminal_closure,
    )
    try:
        await _launch_exact_short(
            manager, execution_id=execution_id, project_id=project.id,
            operation=lambda run_id: service.run_short(
                project.id, run_id=run_id, use_crewai=True,
            ),
            terminal_finalizer=terminal_finalizer,
            already_reserved=True,
        )
    finally:
        close = getattr(registry, "close", None)
        if callable(close):
            closed = close()
            if inspect.isawaitable(closed):
                await closed
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
        }
        raise RuntimeError(
            "FULL_SHORT_SUPERVISED_RUN_NOT_COMPLETED:"
            + json.dumps(diagnostic, ensure_ascii=True, sort_keys=True)
        )
    completion = closure_state.get("completion")
    if not isinstance(completion, dict):
        raise RuntimeError("FULL_SHORT_COMPLETION_NOT_COMMITTED_AFTER_SAGA_CLEANUP")
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
    raw = args.authorization.read_bytes()
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    if actual_sha256 != args.activated_sha256:
        raise SystemExit("ACTIVATED_AUTHORIZATION_SHA256_MISMATCH")
    try:
        authorization, preflight = preflight_full_short_control_plane(
            args, raw,
            external_actions_enabled=args.execute,
        )
    except Exception as exc:
        raise SystemExit(f"FULL_SHORT_PREFLIGHT_FAILED:{exc}") from exc
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
