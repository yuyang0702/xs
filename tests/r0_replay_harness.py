from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from novel_flywheel.db import Database
from novel_flywheel.models import ModelResult
from novel_flywheel.projects import ProjectCreate, ProjectStore
from novel_flywheel.skills import SkillGate, SkillScanner
from novel_flywheel.workflows import WorkflowService

from r0_incident_corpus import HIGH_FREQUENCY_INCIDENT_KEYS
from test_workflows import FakeGateway, make_prompt_skills


class IncidentReplayGateway(FakeGateway):
    """Offline provider that injects one family-shaped planning response."""

    def __init__(self, family: str, variant: int) -> None:
        super().__init__()
        self.family = family
        self.variant = variant
        self.calls: list[dict[str, Any]] = []
        self._planning_attempt = 0
        self._valid_planning: ModelResult | None = None

    @staticmethod
    def _planning_drift(variant: int) -> str:
        payloads: list[dict[str, Any]] = [
            {"version": 2, "initial_state": "state", "segments": []},
            {"version": 1, "initial_state": "state", "segments": []},
            {"version": 2, "initial_state": "", "segments": []},
            {"version": 2, "segments": []},
            {
                "version": 2,
                "initial_state": "state",
                "segments": [{"kind": "terminal", "segment": 99,
                              "title": "drift", "events": []}],
            },
        ]
        return json.dumps(payloads[variant % len(payloads)], ensure_ascii=False)

    @staticmethod
    def _parser_shape(valid: str, variant: int) -> str:
        wrappers = [
            "```json\n%s\n```",
            "```JSON\n%s\n```",
            "```\n%s\n```",
            "\ufeff%s",
            " \n\t%s\n ",
            "MODEL_OUTPUT:\n%s",
            "Here is the requested JSON:\n%s",
            "%s\nEND_JSON",
            "<json>\n%s\n</json>",
            "RESULT = %s",
            "response:\n```json\n%s\n```",
        ]
        return wrappers[variant % len(wrappers)] % valid

    async def complete(self, role, system, user, max_output_tokens=None):
        self.calls.append({
            "role": role,
            "system_sha256": hashlib.sha256(system.encode("utf-8")).hexdigest(),
            "user_sha256": hashlib.sha256(user.encode("utf-8")).hexdigest(),
            "max_output_tokens": max_output_tokens,
            "provider": "offline-deterministic",
        })
        if "IR_FIRST_SHORT_PLANNING_V2" in user:
            self._planning_attempt += 1
            if self._valid_planning is None:
                self._valid_planning = await super().complete(
                    role, system, user, max_output_tokens=max_output_tokens,
                )
                if self.family == "planning.structure_drift":
                    text = self._planning_drift(self.variant)
                else:
                    text = self._parser_shape(
                        self._valid_planning.text, self.variant,
                    )
                return ModelResult(text, {
                    **self._valid_planning.receipt,
                    "provider_id": "r0-offline",
                    "model_id": "r0-deterministic",
                    "finish_reason": "stop",
                })
            return self._valid_planning
        return await super().complete(
            role, system, user, max_output_tokens=max_output_tokens,
        )


def high_frequency_incidents(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item for item in manifest["incidents"]
        if item["current_incident_key"] in HIGH_FREQUENCY_INCIDENT_KEYS
    ]


async def replay_incident(
    root: Path, incident: dict[str, Any], *, variant: int,
) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    db = Database(root / "replay-only.db")
    db.migrate()
    store = ProjectStore(db, root / "isolated-projects")
    project = store.create(ProjectCreate(
        title=f"R0 {variant:02d}",
        mode="short",
        genre="suspense",
        premise="Deterministic replay-only reliability validation.",
        target_words=6_000,
    ))
    skill_root = root / "skills"
    make_prompt_skills(skill_root)
    family = str(incident["current_reclassified_family"])
    gateway = IncidentReplayGateway(family, variant)
    service = WorkflowService(
        db, store, gateway, SkillGate(db, SkillScanner([skill_root])),
    )
    # Keep the physical Windows path short while the evidence retains the
    # explicit logical r0-replay namespace.
    run_id = f"r0r-{incident['incident_id'][-12:]}"
    error: BaseException | None = None
    try:
        await service.run_short(
            project.id, use_crewai=False, run_id=run_id,
        )
    except BaseException as exc:  # evidence captures the terminal chain
        error = exc
    run = db.get_run(run_id)
    events = db.list_run_events(run_id)
    event_types = [str(item["event_type"]) for item in events]
    audit_rows: list[dict[str, Any]] = []
    audit_root = (
        project.path / "runs" / run_id / "outputs" / "conversion-audits"
    )
    for path in sorted(audit_root.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        audit_rows.append({
            "contract_name": payload.get("contract_name"),
            "method": payload.get("method"),
            "semantic_valid": payload.get("semantic_valid"),
            "failure_code": payload.get("failure_code") or None,
            "raw_sha256": payload.get("raw_sha256"),
        })
    planning_completed = "planning_ir_first_compiled" in event_types
    workflow_recovered = bool(run and run["status"] == "completed" and error is None)
    controlled_event = next((
        item for item in events
        if item["event_type"] in {"waiting_provider", "waiting_user"}
    ), None)
    final_outcome = (
        "WORKFLOW_RECOVERED" if workflow_recovered
        else "CONTROLLED_NONTERMINAL" if controlled_event
        else "STILL_TERMINAL_SAME_FAMILY"
    )
    if error is not None and family not in str(error):
        final_outcome = "STILL_TERMINAL_DIFFERENT_FAMILY"
    return {
        "incident_id": incident["incident_id"],
        "historical_family": family,
        "replayability": incident["replayability"],
        "synthetic": True,
        "isolation_namespace": "r0-replay",
        "database_name": "replay-only.db",
        "provider": "offline-deterministic",
        "paid_llm_calls": 0,
        "model_stage_attempts": len(gateway.calls),
        "ordered_model_roles": [item["role"] for item in gateway.calls],
        "planning_model_attempts": gateway._planning_attempt,
        "boundary_recovered": planning_completed,
        "stage_recovered": planning_completed,
        "workflow_recovered": workflow_recovered,
        "controlled_nonterminal": controlled_event is not None,
        "final_terminal_outcome": final_outcome,
        "terminal_error_type": type(error).__name__ if error else None,
        "terminal_error": str(error) if error else None,
        "protocol_retry_attempts": sum(
            1 for item in event_types if "protocol_retry" in item
        ),
        "local_normalize_successes": sum(
            1 for item in event_types
            if item in {"contract_adapter_applied", "contract_syntax_repaired"}
        ),
        "conversion_audits": audit_rows,
        "route_fallback_attempts": sum(
            1 for item in event_types if "fallback" in item
        ),
        "causal_chain": [
            {
                "sequence": index,
                "stage": item.get("stage"),
                "severity": item.get("severity"),
                "event_type": item.get("event_type"),
            }
            for index, item in enumerate(events, 1)
            if item.get("event_type") in {
                "contract_adapter_applied",
                "contract_syntax_repaired",
                "protocol_receipt_route_failed",
                "planning_ir_first_compiled",
                "completed",
                "failed",
                "waiting_provider",
                "waiting_user",
            } or "protocol_retry" in str(item.get("event_type"))
        ],
    }
