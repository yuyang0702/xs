"""Repair re-entry, Candidate containment, and masking characterization."""

from __future__ import annotations

import ast
import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from novel_flywheel.models import ModelResult
from novel_flywheel.skills import SkillGate, SkillScanner
from novel_flywheel.workflows import (
    DraftSemanticValidationError,
    WorkflowService,
)

from test_workflows import (
    FakeGateway,
    _attach_short_revision_semantic_authority,
    _short_revision_service,
    draft_semantic_receipt,
    make_prompt_skills,
)


REPAIR_VARIANTS = (
    "malformed_output",
    "wrapper_output",
    "domain_invalid",
    "provider_truncation",
    "primary_fallback_double_failure",
    "fix_a_break_b",
    "cleanup_secondary_exception",
)


class RepairFaultGateway(FakeGateway):
    def __init__(self, variant: str, source: str) -> None:
        super().__init__()
        if variant not in REPAIR_VARIANTS:
            raise ValueError(f"unknown Repair variant: {variant}")
        self.variant = variant
        self.source = source
        self.repair_calls: list[dict[str, Any]] = []
        self.validation_calls = 0

    def _valid_repair(self) -> str:
        return self.source.replace("逐页核对", "逐页细查", 1)

    def _repair_result(self, role: str, route: str) -> ModelResult:
        index = len(self.repair_calls) + 1
        call = {"index": index, "role": role, "route": route}
        self.repair_calls.append(call)
        if self.variant in {
            "primary_fallback_double_failure", "cleanup_secondary_exception",
        }:
            call["outcome"] = "transport_failure"
            raise ConnectionError(f"offline-{route}-repair-failure")
        valid = self._valid_repair()
        if index > 1:
            text = valid
        elif self.variant == "malformed_output":
            text = '{"repair":'
        elif self.variant == "wrapper_output":
            text = f"```text\n{valid}\n```"
        elif self.variant == "domain_invalid":
            text = self.source.replace("林晚逐页核对", "错误执行者逐页核对", 1)
        elif self.variant == "provider_truncation":
            text = self.source[: max(1, len(self.source) // 2)]
        elif self.variant == "fix_a_break_b":
            text = valid.replace("锚点不变", "锚点已破坏")
        else:
            text = valid
        finish_reason = (
            "max_tokens"
            if self.variant == "provider_truncation" and index == 1
            else "stop"
        )
        call.update({
            "outcome": "provider_response",
            "finish_reason": finish_reason,
            "partial_response": finish_reason == "max_tokens",
        })
        return ModelResult(text, {
            "role": role,
            "provider_id": "r0e-offline",
            "model_id": f"r0e-{route}",
            "model_name": f"r0e-{route}",
            "finish_reason": finish_reason,
            "input_tokens": 128,
            "output_tokens": 64,
            "provider_completeness": (
                "incomplete" if finish_reason == "max_tokens" else "complete"
            ),
        })

    def _semantic_result(self, role: str, user: str) -> ModelResult:
        self.validation_calls += 1
        contract = json.loads(re.search(
            r"TASK CONTRACT: (\{[^\n]+\})", user,
        ).group(1))
        prose = user.split("PROSE:\n", 1)[1]
        receipt = draft_semantic_receipt(contract, prose)
        if "错误执行者" in prose:
            key = "beat_receipts" if receipt.get("beat_receipts") else "event_receipts"
            if key == "beat_receipts":
                receipt[key][0]["actor_action_valid"] = False
        return ModelResult(json.dumps(receipt, ensure_ascii=False), {
            "role": role,
            "provider_id": "r0e-offline",
            "model_id": "r0e-review",
            "model_name": "r0e-review",
            "finish_reason": "stop",
        })

    @staticmethod
    def _is_repair(user: str) -> bool:
        return "ATOMIC_SEMANTIC_PROSE_REPAIR" in user

    @staticmethod
    def _is_semantic_validation(user: str) -> bool:
        return "DRAFT_SEMANTIC_VALIDATION" in user

    async def complete(self, role, system, user, max_output_tokens=None):
        if self._is_repair(user):
            return self._repair_result(role, "primary")
        if self._is_semantic_validation(user):
            return self._semantic_result(role, user)
        return await super().complete(
            role, system, user, max_output_tokens=max_output_tokens,
        )

    async def complete_primary(
        self, role, system, user, max_output_tokens=None,
    ):
        if self._is_repair(user):
            return self._repair_result(role, "primary")
        if self._is_semantic_validation(user):
            return self._semantic_result(role, user)
        return await super().complete_primary(
            role, system, user, max_output_tokens=max_output_tokens,
        )

    async def complete_configured_fallback(
        self, role, system, user, max_output_tokens=None,
    ):
        if self._is_repair(user):
            return self._repair_result(role, "configured_fallback")
        if self._is_semantic_validation(user):
            return self._semantic_result(role, user)
        return await super().complete(
            role, system, user, max_output_tokens=max_output_tokens,
        )


def repair_reentry_matrix(root: Path) -> dict[str, Any]:
    source = root / "src" / "novel_flywheel" / "workflows.py"
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    functions = {
        node.name: node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    targets = (
        "_repair_short_plan_local_event_segment",
        "_repair_short_plan_adaptation_capacity_split",
        "_repair_short_plan_adaptation_segments",
        "_repair_short_revision_semantic_group",
        "_repair_polish_semantic_segment",
        "_close_short_maintenance_window",
        "_close_short_maintenance_authority",
    )
    rows = []
    for name in targets:
        node = functions[name]
        stage_calls = []
        for call in ast.walk(node):
            if not (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr in {"_stage", "_stage_with_role_fallback"}
            ):
                continue
            keywords = {item.arg for item in call.keywords}
            stage_calls.append({
                "callee": call.func.attr,
                "execution_spec": "execution_spec" in keywords,
            })
        rows.append({
            "function": name,
            "stage_calls": stage_calls,
            "all_secondary_model_outputs_reenter_contract_runtime": bool(
                stage_calls and all(item["execution_spec"] for item in stage_calls)
            ),
        })
    return {
        "schema": "R0ERepairReentryMatrixV1",
        "source": "src/novel_flywheel/workflows.py",
        "rows": rows,
    }


def _set_locked_fact(service: WorkflowService, project: Any, value: str) -> None:
    state = service.story_states.get(project.id)
    assert state is not None
    data = deepcopy(state.data)
    data["locked_facts"] = [{
        "key": "repair.anchor", "value": value, "source": "r0e",
    }]
    candidate = service.story_states.create_candidate(
        project.id, "quality-source", state.revision,
        "r0e-test-state", hashlib.sha256(value.encode("utf-8")).hexdigest(),
    )
    service.story_states.commit(candidate.id, state.revision, data)


async def run_repair_probe(root: Path, variant: str) -> dict[str, Any]:
    source = (
        "雨落在档案馆外，林晚逐页核对证词和时间，锚点不变。" * 30
        + "她确认记录无误，带着结果离开，锚点不变。" * 20
    )
    service, project, _source, _ledger, _state = _short_revision_service(
        root, [], source=source, target_words=500,
    )
    manifest, integrity = _attach_short_revision_semantic_authority(
        service, project, source,
    )
    run_path = project.path / "runs" / "quality-source"
    contract = service._manifest_segment_contract(
        project, manifest, integrity, manifest.segments[0], source, 1,
    )
    if variant == "fix_a_break_b":
        _set_locked_fact(service, project, "锚点不变")
    skill_root = root / "r0e-skills"
    make_prompt_skills(skill_root)
    service.skills = SkillGate(
        service.db, SkillScanner([skill_root]),
    )
    gateway = RepairFaultGateway(variant, source)
    service.gateway = gateway
    outputs = run_path / "outputs"
    best_path = outputs / "best-candidate.md"
    checkpoint_path = outputs / "quality-checkpoint.json"
    # Bind the fixture to the same newline-normalized text hash used by the
    # production resume reader on Windows.  This is fixture repair only; the
    # production checkpoint implementation is not changed.
    checkpoint_payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    integrity_path = outputs / "polish-integrity.json"
    checkpoint_payload["narrative_integrity"]["sha256"] = hashlib.sha256(
        integrity_path.read_text(encoding="utf-8").encode("utf-8")
    ).hexdigest()
    checkpoint_path.write_text(
        json.dumps(checkpoint_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    best_before = best_path.read_bytes()
    checkpoint_before = checkpoint_path.read_bytes()
    original_add_event = service.db.add_run_event
    if variant == "cleanup_secondary_exception":
        def cleanup_failure(*args, **kwargs):
            event_type = args[2] if len(args) > 2 else kwargs.get("event_type")
            if event_type == "polish_semantic_repair_unavailable":
                raise OSError("offline cleanup evidence failure")
            return original_add_event(*args, **kwargs)
        service.db.add_run_event = cleanup_failure  # type: ignore[method-assign]
    result = None
    error: BaseException | None = None
    try:
        result = await service._repair_polish_semantic_segment(
            "quality-source", run_path, project, "constraints", contract,
            source, source.replace("林晚逐页核对", "错误执行者逐页核对", 1),
            [], DraftSemanticValidationError(contract.task_id, [{
                "code": "actor_action", "message": "wrong actor",
            }]), suffix="-r0e",
        )
    except BaseException as exc:
        error = exc
    finally:
        service.db.add_run_event = original_add_event  # type: ignore[method-assign]
    best_after = best_path.read_bytes()
    checkpoint_after = checkpoint_path.read_bytes()
    resumed, resume_source = WorkflowService._short_checkpoint_manuscript(
        outputs, 1,
    )
    repaired = result[0] if result is not None else None
    repaired_hash = (
        hashlib.sha256(repaired.encode("utf-8")).hexdigest()
        if repaired is not None else None
    )
    exception_chain: list[str] = []
    cursor = error
    seen: set[int] = set()
    while cursor is not None and id(cursor) not in seen:
        seen.add(id(cursor))
        exception_chain.append(type(cursor).__name__)
        cursor = cursor.__cause__ or cursor.__context__
    primary_in_context = exception_chain[1] if len(exception_chain) > 1 else None
    contained = (
        best_before == best_after
        and checkpoint_before == checkpoint_after
        and resumed == source
        and resume_source == "best-candidate.md"
    )
    return {
        "variant": variant,
        "path": "WorkflowService._repair_polish_semantic_segment",
        "same_contract_runtime": False,
        "repair_recovered": result is not None,
        "repair_output_hash": repaired_hash,
        "boundary_recovered": result is not None,
        "stage_recovered": result is not None,
        "workflow_recovered": None,
        "controlled_nonterminal": result is None and error is None and contained,
        "final_outcome": (
            "REPAIR_RECOVERED" if result is not None
            else "CLEANUP_SECONDARY_MASKED_PRIMARY" if error is not None
            else "CONTROLLED_CONTAINMENT" if contained
            else "REPAIR_TERMINAL"
        ),
        "prior_best_hash": hashlib.sha256(best_before).hexdigest(),
        "prior_best_preserved": best_before == best_after,
        "failed_repair_overwrote_best": best_before != best_after,
        "checkpoint_preserved": checkpoint_before == checkpoint_after,
        "resume_source": resume_source,
        "resume_hash": hashlib.sha256(resumed.encode("utf-8")).hexdigest(),
        "controlled_containment": contained,
        "terminal_error_type": type(error).__name__ if error else None,
        "primary_error_in_context": primary_in_context,
        "exception_chain": exception_chain,
        "root_cause_preserved": not (
            variant == "cleanup_secondary_exception" and error is not None
        ),
        "repair_calls": list(gateway.repair_calls),
        "semantic_validator_calls": gateway.validation_calls,
        "paid_llm_calls": 0,
        "historical_incident_binding": None,
    }
