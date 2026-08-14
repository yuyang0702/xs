"""Offline production-boundary and paired-control Maintenance evidence."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from novel_flywheel.contract_runtime import ExecutableContractSpec
from novel_flywheel.db import Database
from novel_flywheel.generated_artifacts import ARTIFACT_CONTRACT_REGISTRY
from novel_flywheel.maintenance_authority import (
    MAINTENANCE_WINDOW_RECEIPT_VERSION,
    MaintenanceWindowReceiptV1,
    adapt_maintenance_window_payload,
    build_maintenance_window_contracts,
    maintenance_window_prompt,
    receipt_to_maintenance_candidate,
)
from novel_flywheel.models import ModelResult
from novel_flywheel.projects import ProjectCreate, ProjectStore
from novel_flywheel.skills import SkillGate, SkillScanner
from novel_flywheel.story_state import StoryStateStore
from novel_flywheel.structured_artifacts import StructuredArtifactContract
from novel_flywheel.workflows import WorkflowService

from test_workflows import FakeGateway, make_prompt_skills


MAINTENANCE_VARIANTS = (
    "malformed_json",
    "fenced_json",
    "missing_field",
    "wrong_container",
    "version_mismatch",
    "domain_invalid",
    "provider_truncation",
    "primary_fallback_double_failure",
)


class MaintenanceFaultGateway(FakeGateway):
    """Replace only the paid Maintenance network boundary."""

    def __init__(self, variant: str) -> None:
        super().__init__()
        if variant not in MAINTENANCE_VARIANTS:
            raise ValueError(f"unknown Maintenance variant: {variant}")
        self.variant = variant
        self.maintenance_calls: list[dict[str, Any]] = []
        self._maintenance_mode = False

    @staticmethod
    def _valid(window: bool) -> str:
        if window:
            return json.dumps({
                "version": MAINTENANCE_WINDOW_RECEIPT_VERSION,
                "facts": [],
                "state_deltas": [],
                "state_transitions": [],
                "world_rules": [],
                "timeline": [],
            }, ensure_ascii=False)
        return json.dumps({"facts": [], "state": {}}, ensure_ascii=False)

    def _fault_text(self, *, window: bool) -> str:
        valid = self._valid(window)
        if self.variant == "malformed_json":
            return '{"facts": ['
        if self.variant == "fenced_json":
            return f"```json\n{valid}\n```"
        if self.variant == "missing_field":
            return json.dumps(
                {"version": MAINTENANCE_WINDOW_RECEIPT_VERSION}
                if window else {"state": {}},
                ensure_ascii=False,
            )
        if self.variant == "wrong_container":
            return json.dumps({"payload": json.loads(valid)}, ensure_ascii=False)
        if self.variant == "version_mismatch":
            payload = json.loads(valid)
            payload["version"] = "maintenance-window-receipt-v0"
            return json.dumps(payload, ensure_ascii=False)
        if self.variant == "domain_invalid":
            if window:
                return json.dumps({
                    "version": MAINTENANCE_WINDOW_RECEIPT_VERSION,
                    "facts": [{
                        "key": "ending.location",
                        "value": "不存在的地点",
                        "evidence": "这段证据不在正文中",
                    }],
                    "state_deltas": [],
                    "state_transitions": [],
                    "world_rules": [],
                    "timeline": [],
                }, ensure_ascii=False)
            return json.dumps({
                "facts": [
                    {"fact_key": "ending.location", "value": "上海"},
                    {"fact_key": "ending.location", "value": "北京"},
                ],
                "state": {},
            }, ensure_ascii=False)
        if self.variant == "provider_truncation":
            return valid[: max(1, len(valid) // 2)]
        return valid

    @staticmethod
    def _is_window(user: str) -> bool:
        return "maintenance-window-request-v1" in user

    def _is_maintenance_call(self, role: str, user: str) -> bool:
        if role == "maintenance" or self._is_window(user):
            self._maintenance_mode = True
            return True
        return (
            self._maintenance_mode
            and role == "planning"
            and "IR_FIRST_SHORT_PLANNING" not in user
        )

    def _maintenance_result(self, role: str, user: str, route: str) -> ModelResult:
        window = self._is_window(user)
        index = len(self.maintenance_calls) + 1
        call = {
            "index": index,
            "role": role,
            "route": route,
            "window": window,
            "variant": self.variant,
        }
        self.maintenance_calls.append(call)
        if self.variant == "primary_fallback_double_failure":
            call["outcome"] = "transport_failure"
            raise ConnectionError(f"offline-{route}-maintenance-failure")
        text = self._fault_text(window=window) if index == 1 else self._valid(window)
        finish_reason = (
            "max_tokens" if self.variant == "provider_truncation" and index == 1
            else "stop"
        )
        call.update({
            "outcome": "provider_response",
            "finish_reason": finish_reason,
            "provider_completeness": (
                "incomplete" if finish_reason == "max_tokens" else "complete"
            ),
            "partial_response": finish_reason == "max_tokens",
        })
        return ModelResult(text, {
            "role": role,
            "provider_id": "r0e-offline",
            "model_id": f"r0e-{route}",
            "model_name": f"r0e-{route}",
            "finish_reason": finish_reason,
            "input_tokens": 64,
            "output_tokens": 32,
            "requested_max_output_tokens": 32,
            "provider_completeness": (
                "incomplete" if finish_reason == "max_tokens" else "complete"
            ),
        })

    async def complete(self, role, system, user, max_output_tokens=None):
        if self._is_maintenance_call(role, user):
            return self._maintenance_result(role, user, "primary")
        return await super().complete(
            role, system, user, max_output_tokens=max_output_tokens,
        )

    async def complete_primary(
        self, role, system, user, max_output_tokens=None,
    ):
        if self._is_maintenance_call(role, user):
            return self._maintenance_result(role, user, "primary")
        return await super().complete_primary(
            role, system, user, max_output_tokens=max_output_tokens,
        )

    async def complete_configured_fallback(
        self, role, system, user, max_output_tokens=None,
    ):
        if self._is_maintenance_call(role, user):
            return self._maintenance_result(role, user, "configured_fallback")
        return await super().complete(
            role, system, user, max_output_tokens=max_output_tokens,
        )


def _service(root: Path, variant: str, *, window: bool) -> tuple[
    WorkflowService, Any, MaintenanceFaultGateway,
]:
    root.mkdir(parents=True, exist_ok=True)
    db = Database(root / "r0e-only.db")
    db.migrate()
    store = ProjectStore(db, root / "isolated-projects")
    project = store.create(ProjectCreate(
        title="R0E Maintenance",
        mode="short",
        genre="suspense",
        premise="Offline Maintenance boundary evidence.",
        target_words=6_000,
    ))
    StoryStateStore(db).ensure(project.id, project.path)
    skill_root = root / "skills"
    make_prompt_skills(skill_root)
    if window:
        db.save_provider(
            provider_id="r0e-provider", name="R0E", protocol="openai",
            base_url="https://offline.invalid", auth_type="bearer",
            timeout_seconds=1, extra_headers={},
        )
        for model_id in ("r0e-small", "r0e-fallback"):
            db.save_model(
                model_id=model_id, provider_id="r0e-provider",
                display_name=model_id, model_name=model_id,
                context_window=256, max_output_tokens=64,
            )
        db.save_role_binding(
            "maintenance", "r0e-provider", "r0e-small",
            "r0e-provider", "r0e-fallback",
        )
    gateway = MaintenanceFaultGateway(variant)
    service = WorkflowService(
        db, store, gateway, SkillGate(db, SkillScanner([skill_root])),
    )
    return service, project, gateway


def _event_projection(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keep = {
        "stage_started", "stage_completed", "stage_failed",
        "contract_adapter_applied", "contract_syntax_repaired",
        "model_fallback", "output_limit_expanded", "output_limit_complete",
        "completed", "failed", "waiting_provider", "waiting_user",
    }
    return [
        {
            "sequence": index,
            "stage": event.get("stage"),
            "event_type": event.get("event_type"),
            "severity": event.get("severity"),
        }
        for index, event in enumerate(events, 1)
        if event.get("event_type") in keep
        or "protocol" in str(event.get("event_type"))
    ]


async def run_current_maintenance_workflow(
    root: Path, variant: str, *, window: bool,
) -> dict[str, Any]:
    service, project, gateway = _service(root, variant, window=window)
    variant_index = MAINTENANCE_VARIANTS.index(variant)
    run_id = f"r0em-{'w' if window else 'n'}{variant_index}"
    error: BaseException | None = None
    try:
        await service.run_short(project.id, use_crewai=False, run_id=run_id)
    except BaseException as exc:
        error = exc
    run = service.db.get_run(run_id)
    events = service.db.list_run_events(run_id)
    event_types = [str(event.get("event_type")) for event in events]
    completed = bool(run and run["status"] == "completed" and error is None)
    controlled = next((
        item for item in events
        if item.get("event_type") in {"waiting_provider", "waiting_user"}
    ), None)
    maintenance_entered = any(
        event.get("stage") == "maintenance"
        and event.get("event_type") == "stage_started"
        for event in events
    )
    maintenance_stage_completed = any(
        event.get("stage") == "maintenance"
        and event.get("event_type") == "stage_completed"
        for event in events
    )
    final_outcome = (
        "WORKFLOW_RECOVERED" if completed
        else "CONTROLLED_NONTERMINAL" if controlled is not None
        else "TERMINAL"
    )
    return {
        "path": "current_bypass",
        "workflow_shape": "production_workflow",
        "mode": "window" if window else "normal",
        "variant": variant,
        "database_name": "r0e-only.db",
        "provider": "offline-deterministic",
        "paid_llm_calls": 0,
        "maintenance_entered": maintenance_entered,
        "unified_contract_runtime": False,
        "boundary_recovered": maintenance_stage_completed,
        "stage_recovered": maintenance_stage_completed,
        "workflow_recovered": completed,
        "controlled_nonterminal": controlled is not None,
        "final_outcome": final_outcome,
        "run_status": run["status"] if run else None,
        "terminal_error_type": type(error).__name__ if error else None,
        "maintenance_calls": list(gateway.maintenance_calls),
        "protocol_retry_attempts": sum(
            "protocol" in event_type and "retry" in event_type
            for event_type in event_types
        ),
        "route_fallback_attempts": sum(
            "fallback" in event_type for event_type in event_types
        ),
        "causal_chain": _event_projection(events),
    }


def _normal_spec(
    service: WorkflowService,
    run_path: Path,
    run_id: str,
    state_data: Mapping[str, object],
    manuscript: str,
) -> ExecutableContractSpec:
    def complete(raw: str) -> bool:
        payload = service._convert_generated_object(
            raw, run_path, contract_name="short_maintenance_facts",
        )
        safe, conflicts = service._partition_short_maintenance_proposal(
            state_data, payload, run_id=run_id, manuscript_text=manuscript,
        )
        if conflicts:
            raise ValueError("normal Maintenance domain conflict")
        service._merge_short_maintenance_authority(
            state_data, safe, run_id=run_id, manuscript_text=manuscript,
        )
        return True

    return service._structured_stage_spec(
        "short_maintenance_facts",
        completion_check=complete,
        runtime_authority={"source": "r0e-paired-control"},
        retry_domain_failures=True,
    )


def _window_spec(contract, manuscript: str) -> ExecutableContractSpec:
    def normalize(value: object) -> dict[str, Any] | None:
        try:
            return MaintenanceWindowReceiptV1.model_validate(value).model_dump(
                mode="json", by_alias=True,
            )
        except (TypeError, ValueError):
            return None

    return ExecutableContractSpec(
        contract_name="maintenance_window_receipt",
        structured_contract=StructuredArtifactContract(
            name="maintenance_window_receipt",
            version=ARTIFACT_CONTRACT_REGISTRY[
                "maintenance_window_receipt"
            ].version,
            schema=MaintenanceWindowReceiptV1.model_json_schema(),
            runtime_authority={
                "window_id": contract.window_id,
                "text_sha256": contract.text_sha256,
            },
        ),
        semantic_normalizer=normalize,
        domain_validator=lambda payload: adapt_maintenance_window_payload(
            payload, contract=contract, manuscript=manuscript,
        ),
        retry_domain_failures=True,
    )


async def run_contract_runtime_control(
    root: Path, variant: str, *, window: bool,
) -> dict[str, Any]:
    service, project, gateway = _service(root, variant, window=False)
    variant_index = MAINTENANCE_VARIANTS.index(variant)
    run_id = f"r0ec-{'w' if window else 'n'}{variant_index}"
    service.db.create_run(
        run_id, project.id, "short-story", status="running",
    )
    run_path = project.path / "runs" / run_id
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()
    state = service.story_states.get(project.id)
    assert state is not None
    manuscript = "结局时调查员留在上海并公开底账。"
    contract = build_maintenance_window_contracts(
        manuscript,
        entry_state_sha256=(
            __import__(
                "novel_flywheel.maintenance_authority",
                fromlist=["canonical_sha256"],
            ).canonical_sha256(
                service._short_maintenance_state_authority(state.data)
            )
        ),
        target_characters=400,
    )[0]
    user = (
        maintenance_window_prompt(
            contract, manuscript,
            entry_authority=service._short_maintenance_state_authority(
                state.data,
            ),
            repair=None,
        )
        if window else manuscript
    )
    spec = (
        _window_spec(contract, manuscript)
        if window else _normal_spec(
            service, run_path, run_id, state.data, manuscript,
        )
    )
    error: BaseException | None = None
    boundary_recovered = False
    try:
        raw = await service._stage(
            run_id, run_path, project, "maintenance", "constraints", user,
            allow_tools=False, bounded_protocol_output=True,
            execution_spec=spec,
        )
        payload = service._convert_generated_object(
            str(raw), run_path,
            contract_name=(
                "maintenance_window_receipt" if window
                else "short_maintenance_facts"
            ),
        )
        if window:
            envelope = adapt_maintenance_window_payload(
                payload, contract=contract, manuscript=manuscript,
            )
            candidate = receipt_to_maintenance_candidate(envelope)
        else:
            candidate = payload
        safe, conflicts = service._partition_short_maintenance_proposal(
            state.data, candidate, run_id=run_id, manuscript_text=manuscript,
        )
        if conflicts:
            raise ValueError("paired control retained Maintenance conflict")
        service._merge_short_maintenance_authority(
            state.data, safe, run_id=run_id, manuscript_text=manuscript,
        )
        boundary_recovered = True
    except BaseException as exc:
        error = exc
    events = service.db.list_run_events(run_id)
    return {
        "path": "contract_runtime_control",
        "workflow_shape": "paired_boundary_control",
        "mode": "window" if window else "normal",
        "variant": variant,
        "database_name": "r0e-only.db",
        "provider": "offline-deterministic",
        "paid_llm_calls": 0,
        "unified_contract_runtime": True,
        "boundary_recovered": boundary_recovered,
        "stage_recovered": boundary_recovered,
        "workflow_recovered": None,
        "controlled_nonterminal": False,
        "final_outcome": (
            "BOUNDARY_RECOVERED" if boundary_recovered else "BOUNDARY_TERMINAL"
        ),
        "terminal_error_type": type(error).__name__ if error else None,
        "terminal_error": str(error) if error else None,
        "maintenance_calls": list(gateway.maintenance_calls),
        "causal_chain": _event_projection(events),
    }


def classify_paired_result(
    current: Mapping[str, Any], control: Mapping[str, Any],
) -> tuple[str, str]:
    if (
        current["workflow_recovered"] is False
        and control["boundary_recovered"] is True
    ):
        return (
            "BYPASS_CAUSAL",
            "first divergence: conversion/recovery occurs outside versus inside "
            "the Contract Runtime; the control crosses the same domain merge",
        )
    if (
        current["workflow_recovered"] is True
        and control["boundary_recovered"] is True
    ) or (
        current["workflow_recovered"] is False
        and control["boundary_recovered"] is False
    ):
        return "NO_DIFFERENTIAL_EFFECT", "paired recovery outcome is equal"
    return (
        "BYPASS_CORRELATED",
        "paired paths differ, but the differential does not isolate a worse bypass outcome",
    )


async def build_maintenance_recovery_matrix(root: Path) -> dict[str, Any]:
    rows = []
    for variant in MAINTENANCE_VARIANTS:
        for window in (False, True):
            case_root = root / f"{MAINTENANCE_VARIANTS.index(variant)}{'w' if window else 'n'}"
            current = await run_current_maintenance_workflow(
                case_root / "current", variant, window=window,
            )
            control = await run_contract_runtime_control(
                case_root / "control", variant, window=window,
            )
            classification, first_divergent_node = classify_paired_result(
                current, control,
            )
            rows.append({
                "mode": "window" if window else "normal",
                "variant": variant,
                "current_boundary_recovered": current["boundary_recovered"],
                "current_stage_recovered": current["stage_recovered"],
                "current_workflow_recovered": current["workflow_recovered"],
                "current_controlled_nonterminal": current[
                    "controlled_nonterminal"
                ],
                "current_final_outcome": current["final_outcome"],
                "current_error": current["terminal_error_type"],
                "current_calls": len(current["maintenance_calls"]),
                "control_boundary_recovered": control["boundary_recovered"],
                "control_error": control["terminal_error_type"],
                "control_calls": len(control["maintenance_calls"]),
                "classification": classification,
                "first_divergent_node": first_divergent_node,
                "historical_incident_binding": None,
                "historical_count": 0,
                "paid_llm_calls": 0,
            })
    return {
        "schema": "R0EMaintenanceRecoveryCoverageMatrixV1",
        "case_count": len(rows),
        "rows": rows,
        "historical_metric_effect": "none_mechanism_probe_only",
    }
