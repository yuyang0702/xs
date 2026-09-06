"""Private Full Short replay through the real one-shot runner/control-plane.

Two isolated copies are used.  The first discovers the deterministic call
plan.  The second renders canonical authorization from that plan and executes
the production preflight, durable store, task manager, WorkflowService,
registry and provider adapters.  Only the final ``httpx`` transport and an
in-memory placeholder secret are replaced; no external request is possible.
"""

from __future__ import annotations

import argparse
import asyncio
from contextlib import nullcontext
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Awaitable, Callable, Mapping

import httpx

from novel_flywheel.context_policy import estimate_input_tokens
from novel_flywheel.contract_runtime import (
    _FINAL_ARTIFACT_COMPLETION_SYSTEM_SUFFIX_V1,
)
from novel_flywheel.db import Database
from novel_flywheel.failure_boundary import failure_evidence_sha256
from novel_flywheel.full_short_execution import (
    FullShortDurableExecutionStoreV1,
    FullShortExecutionPolicyV1,
    LOGICAL_STAGE_RECOVERY_POLICY_V1,
    build_full_short_completion_receipt_v1,
    full_short_logical_stage_id_v1,
    render_full_short_canonical_authorization_v1,
    validate_full_short_canonical_authorization_v1,
)
from novel_flywheel.models import ModelResult
from novel_flywheel.maintenance_authority import (
    validate_maintenance_reduction,
)
from novel_flywheel.offline_http_transport import (
    OfflineHttpRequestV1,
    OfflineHttpResponseV1,
    build_offline_http_transport_v1,
)
from novel_flywheel.provider_response_capture import (
    CONTRACT_RUNTIME_INPUT_BYTES,
    PROVIDER_PROTOCOL_INPUT_BYTES,
    ProviderResponseCaptureStoreV1,
    parse_provider_protocol_input_bytes_v1,
)
from novel_flywheel.project_transactions import (
    ProjectMutationJournalV1,
    canonical_json_sha256,
    project_mutation_journal_path,
)
from novel_flywheel.runtime_fingerprint_build import domain_sha256
from novel_flywheel.projects import ProjectStore
from novel_flywheel.providers.http import SingleDispatchTransportPolicyV1
from novel_flywheel.providers.registry import ADAPTERS, ProviderRegistry, ResolvedModel
from novel_flywheel.secrets import MemorySecretStore
from novel_flywheel.stage_capacity import (
    DEFAULT_STAGE_CAPACITY_POLICY_REGISTRY_V1,
)
from novel_flywheel.story_state import StoryStateStore
from novel_flywheel.short_canonical_promotion import (
    MaintenanceProposalInventoryV1,
)
from novel_flywheel.full_short_runtime_kernel import (
    DurableExecutionJournalV1,
    ExecutionState,
)
from novel_flywheel.workflows import (
    validate_short_maintenance_business_complete_v2,
)
from tools.canary.fake_boundary import (
    DeterministicShortBoundary,
    _draft_semantic_receipt,
    _execution_manifest_receipt,
)
from tools.canary.short_completion import COMPLETION_GOAL
from tools.canary.first_trustworthy_full_short_runner import (
    FULL_SHORT_BOUND_ROLES,
    FULL_SHORT_REQUIRED_EXECUTION_ROLES,
    _execute_full_short_control_plane_offline,
    collect_live_bindings,
    run_full_short_workflow_path,
)


EXECUTION_ID = "private-current-project-dry-run"
DISCOVERY_ID = "private-current-project-call-plan"
OFFLINE_CONTEXT_MANIFEST_KEY_V1 = (
    "offline_deterministic_context_manifest_v1"
)
OFFLINE_CONTEXT_LIMIT_TOKENS_V1 = 32_768
OFFLINE_CONTEXT_MANIFEST_V1 = {
    "schema": "OfflineDeterministicGatewayContextCapabilityManifestV1",
    "version": 1,
    "context_limit_tokens": OFFLINE_CONTEXT_LIMIT_TOKENS_V1,
    "capacity_policy_registry_sha256": (
        DEFAULT_STAGE_CAPACITY_POLICY_REGISTRY_V1.identity_sha256
    ),
    "scope": "ISOLATED_PRIVATE_DATA_COPY_ONLY",
    "external_actions_enabled": False,
}

_FULL_SHORT_REQUIRED_ARTIFACTS = {
    "planning-semantic-v2.json",
    "short-causal-chain.json",
    "short-execution-index.json",
    "draft.md",
    "polish.md",
    "final-review-evidence.json",
    "quality-report.json",
    "draft-integrity.json",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _domain(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _safe_failure_projection(
    exc: BaseException, *, boundary: str,
) -> dict[str, str]:
    """Retain typed/hash-only diagnostics without persisting exception text."""

    return {
        "exception_type": type(exc).__name__,
        "failure_sha256": failure_evidence_sha256(exc, boundary=boundary),
    }


def _optional_text_sha256(value: object) -> str | None:
    text = str(value or "")
    return hashlib.sha256(text.encode("utf-8")).hexdigest() if text else None


def _executed_physical_attempt_envelopes_v1(
    *, project_root: Path, ledger: dict[str, Any],
    observed_plan: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Join wire observations to their exact persisted capacity plans."""

    capacity_root = (
        project_root / "runs" / EXECUTION_ID / "outputs" / "capacity-plans"
    )
    plans: dict[str, dict[str, Any]] = {}
    for path in capacity_root.glob("*.json"):
        document = json.loads(path.read_text(encoding="utf-8"))
        plan = document.get("plan") if isinstance(document, dict) else None
        if not isinstance(plan, dict):
            continue
        plan_sha256 = str(plan.get("plan_sha256") or "")
        if plan_sha256:
            plans[plan_sha256] = plan
    attempts = list(ledger.get("attempts") or [])
    if len(attempts) != len(observed_plan):
        raise RuntimeError("FULL_SHORT_PHYSICAL_ENVELOPE_ATTEMPT_COUNT_DRIFT")
    result: list[dict[str, Any]] = []
    for call, attempt in zip(observed_plan, attempts, strict=True):
        plan_sha256 = str(attempt.get("capacity_plan_sha256") or "")
        plan = plans.get(plan_sha256)
        if plan is None:
            raise RuntimeError("FULL_SHORT_PHYSICAL_ENVELOPE_PLAN_MISSING")
        layers = {
            str(item.get("layer_id")): item
            for item in (plan.get("layer_projections") or [])
            if isinstance(item, dict)
        }
        relevant = layers.get("relevant_context")
        complete = layers.get("complete_request")
        result.append({
            "ordinal": int(call["ordinal"]),
            "stage": str(attempt.get("stage") or plan.get("stage_id") or ""),
            "role": str(call["role"]),
            "logical_stage_id": str(attempt.get("logical_stage_id") or ""),
            "physical_attempt": int(plan.get("physical_attempt") or 0),
            "physical_attempt_id": str(
                attempt.get("physical_attempt_id")
                or plan.get("physical_attempt_id") or ""
            ),
            "global_physical_attempt_ordinal": (
                attempt.get("global_physical_attempt_ordinal")
                or plan.get("global_physical_attempt_ordinal")
            ),
            "attempt_role": str(
                attempt.get("recovery_family")
                or attempt.get("stage_role") or "NORMAL"
            ),
            "recovery_family": str(
                attempt.get("recovery_family") or "NORMAL"
            ),
            "route": str(attempt.get("bound_lane") or call.get("route_lane") or ""),
            "route_fingerprint": str(call.get("route_fingerprint") or ""),
            "provider_operator": str(call.get("provider_operator") or ""),
            "protocol": str(call.get("protocol") or ""),
            "model_name": str(call.get("model_name") or ""),
            "system_tokens": int(call["system_tokens"]),
            "task_tokens": int(call["task_tokens"]),
            "authority_context_tokens": int(
                plan.get("protected_layer_tokens") or 0
            ),
            "skill_advisory_tokens": int(
                plan.get("advisory_layer_tokens") or 0
            ),
            "manuscript_window_tokens": int(
                (relevant or complete or {}).get("post_transform_tokens") or 0
            ),
            "structured_envelope_tokens": int(
                plan.get("structured_envelope_tokens") or 0
            ),
            "protocol_overhead_tokens": int(
                plan.get("provider_envelope_tokens") or 0
            ),
            "wrapper_and_estimator_margin_tokens": int(
                plan.get("wrapper_and_estimator_margin_tokens") or 0
            ),
            "total_rendered_input_tokens": int(
                plan.get("expected_rendered_input") or 0
            ),
            "rendered_message_utf8_bytes": int(
                call["rendered_message_utf8_bytes"]
            ),
            "provider_wire_payload_utf8_bytes": int(
                call["provider_wire_payload_utf8_bytes"]
            ),
            "provider_wire_payload_estimated_tokens": int(
                call["provider_wire_payload_estimated_tokens"]
            ),
            "safety_headroom": int(plan.get("headroom") or 0),
            "input_envelope_sha256": str(call["input_envelope_sha256"]),
            "capacity_plan_sha256": plan_sha256,
            "compaction_policy_id": str(plan.get("compaction_policy_id") or ""),
            "segmentation_policy_id": str(
                plan.get("segmentation_policy_id") or ""
            ),
            "recovery_overlay_kind": str(
                plan.get("recovery_overlay_kind") or "NONE"
            ),
            "business_desired_output_tokens": int(
                plan.get("final_output_reserve") or 0
            ),
            "stage_specific_output_cap": int(
                plan.get("requested_output_token_cap") or 0
            ),
            "recovery_specific_output_cap": (
                int(plan.get("requested_output_token_cap") or 0)
                if str(attempt.get("stage_role") or "NORMAL") != "NORMAL"
                else None
            ),
            "physical_attempt_requested_output_cap": int(
                plan.get("requested_output_token_cap") or 0
            ),
            "provider_wire_requested_output_cap": int(
                call["provider_wire_requested_output_tokens"]
            ),
            "input_estimator_identity": str(call["input_estimator_identity"]),
            "raw_prompt_persisted": False,
        })
    if any(
        item["physical_attempt_requested_output_cap"]
        != item["provider_wire_requested_output_cap"]
        for item in result
    ):
        raise RuntimeError("FULL_SHORT_OUTPUT_CAP_LINEAGE_DRIFT")
    return result


def _secondary_close_cause(
    primary: Exception, close_error: Exception,
) -> Exception:
    """Retain an existing explicit cause alongside resource-close evidence."""

    existing = primary.__cause__
    if isinstance(existing, Exception) and existing is not close_error:
        return ExceptionGroup(
            "FULL_SHORT_PRIMARY_AND_RESOURCE_CLOSE_CAUSES",
            [existing, close_error],
        )
    return close_error


async def _await_with_registry_close(
    operation: Callable[[], Awaitable[Any]], registry: Any,
) -> Any:
    """Close a registry without replacing the operation's primary failure."""

    try:
        result = await operation()
    except Exception as primary:
        try:
            await registry.close()
        except Exception as close_error:
            raise primary from _secondary_close_cause(primary, close_error)
        raise
    await registry.close()
    return result


def _shutdown_crewai_event_bus() -> None:
    """Drain CrewAI's process-global executor before private-file cleanup."""

    event_bus_module = sys.modules.get("crewai.events.event_bus")
    if event_bus_module is None:
        return
    event_bus = getattr(event_bus_module, "crewai_event_bus", None)
    shutdown = getattr(event_bus, "shutdown", None)
    if not callable(shutdown):
        raise RuntimeError("FULL_SHORT_CREWAI_EVENT_BUS_SHUTDOWN_UNAVAILABLE")
    shutdown(wait=True)


def _cleanup_private_workspace_v1(temporary_directory: Any) -> None:
    """Retry only the Windows non-empty-directory race in our exact temp root."""

    try:
        temporary_directory.cleanup()
        return
    except OSError as exc:
        if getattr(exc, "winerror", None) != 145:
            raise
        last_error: OSError = exc
    root = Path(str(temporary_directory.name)).resolve()
    system_temp_root = Path(tempfile.gettempdir()).resolve()
    if (
        not root.is_relative_to(system_temp_root)
        or not root.name.startswith("full-short-private-")
    ):
        raise RuntimeError("FULL_SHORT_PRIVATE_CLEANUP_TARGET_INVALID")
    for attempt in range(5):
        time.sleep(0.05 * (attempt + 1))
        try:
            shutil.rmtree(root)
            return
        except FileNotFoundError:
            return
        except OSError as exc:
            if getattr(exc, "winerror", None) != 145:
                raise
            last_error = exc
    raise RuntimeError(
        "FULL_SHORT_PRIVATE_CLEANUP_NONEMPTY_RETRY_EXHAUSTED"
    ) from last_error


def _run_with_private_workspace(
    args: argparse.Namespace,
    *,
    temporary_directory_factory: Callable[..., Any] | None = None,
    async_runner: Callable[[Awaitable[dict[str, Any]]], dict[str, Any]] | None = None,
    event_bus_shutdown: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Run the async lifecycle fully before closing global and file resources."""

    create_temporary_directory = (
        temporary_directory_factory or tempfile.TemporaryDirectory
    )
    run_async = async_runner or asyncio.run
    shutdown_event_bus = event_bus_shutdown or _shutdown_crewai_event_bus
    temporary_directory = create_temporary_directory(
        prefix="full-short-private-"
    )
    primary: Exception | None = None
    summary: dict[str, Any] | None = None
    try:
        summary = run_async(
            _run(args, private_root=Path(temporary_directory.name))
        )
    except Exception as exc:
        primary = exc

    close_errors: list[Exception] = []
    for close in (
        shutdown_event_bus,
        lambda: _cleanup_private_workspace_v1(temporary_directory),
    ):
        try:
            close()
        except Exception as exc:
            close_errors.append(exc)
    if close_errors:
        close_error = ExceptionGroup(
            "FULL_SHORT_PRIVATE_RESOURCE_CLOSE_FAILED", close_errors,
        )
        if primary is not None:
            raise primary from _secondary_close_cause(primary, close_error)
        raise close_error
    if primary is not None:
        raise primary
    if summary is None:
        raise RuntimeError("FULL_SHORT_PRIVATE_RUN_SUMMARY_MISSING")
    return summary


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=repo, text=True, encoding="utf-8",
    ).strip()


def _request_messages(payload: dict[str, Any]) -> tuple[str, str]:
    messages = payload.get("messages") or payload.get("input") or []
    system_parts: list[str] = []
    user_parts: list[str] = []
    for item in messages:
        if not isinstance(item, dict):
            continue
        raw = item.get("content") or ""
        if isinstance(raw, list):
            content = "".join(
                str(part.get("text") or "")
                for part in raw if isinstance(part, dict)
            )
        else:
            content = str(raw)
        target = system_parts if item.get("role") == "system" else user_parts
        target.append(content)
    system = str(payload.get("system") or payload.get("instructions") or "")
    return system or "\n\n".join(system_parts), "\n\n".join(user_parts)


def _request_role(system: str, user: str) -> str:
    if any(marker in user for marker in (
        "SHORT_PLAN_ADAPTATION_REVIEW_V2",
        "SHORT_PLAN_ADAPTATION_WHOLE_STORY_REVIEW_V2",
    )):
        return "review"
    if "TARGET READER SIMULATION" in user:
        return "reader_review"
    if any(marker in user for marker in (
        "FULL MANUSCRIPT WINDOW SUMMARY",
        "终审详细事件和伏笔单独分析",
        "REGIONAL EVIDENCE REDUCTION",
        "FULL MANUSCRIPT FINAL ADJUDICATION",
    )):
        return "final_review"
    if "CURRENT_TASK_CONTRACT" in user:
        return "draft"
    if "MANUSCRIPT SEGMENT:\n" in user:
        return "polish"
    upper = system.upper()
    for role in FULL_SHORT_REQUIRED_EXECUTION_ROLES:
        if role.upper().replace("_", " ") in upper:
            return role
    if "MAINTENANCE" in upper or "STORYSTATE" in user.upper():
        return "maintenance"
    return "planning"


def _safe_request_plan_entry_v1(
    *, ordinal: int, protocol: str, destination: str,
    provider_id_sha256: str | None, model_id_sha256: str | None,
    model_name: str | None, route_fingerprint: str | None,
    provider_operator: str | None, route_lane: str | None,
    role: str, contract_marker: str | None, maximum: int,
    payload: dict[str, Any], system: str, user: str,
) -> dict[str, Any]:
    """Project an exact provider-wire request to counts and hashes only."""

    def section_tokens(heading: str) -> int:
        marker = heading + ":\n"
        if marker not in system:
            return 0
        value = system.split(marker, 1)[1].split("\n\n", 1)[0]
        return estimate_input_tokens(marker + value)

    rendered = system + "\n" + user
    rendered_message_sha256 = hashlib.sha256(
        rendered.encode("utf-8")
    ).hexdigest()
    rendered_request_sha256 = hashlib.sha256(
        (system + "\n\0" + user).encode("utf-8")
    ).hexdigest()
    wire_payload = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    entry = {
        "ordinal": ordinal,
        "role": role,
        "route_lane": route_lane,
        "route_fingerprint": route_fingerprint,
        "provider_id_sha256": provider_id_sha256,
        "model_id_sha256": model_id_sha256,
        "model_name": model_name,
        "provider_operator": provider_operator,
        "protocol": protocol,
        "contract_marker": contract_marker,
        "requested_output_tokens": maximum,
        "provider_wire_requested_output_tokens": maximum,
        "system_tokens": estimate_input_tokens(system),
        "task_tokens": estimate_input_tokens(user),
        "authority_context_tokens": sum(
            section_tokens(heading) for heading in (
                "CURRENT_TASK_ENVELOPE",
                "MANDATORY_NARRATIVE_RULES",
                "GLOBAL_STORY_SKELETON",
            )
        ) or estimate_input_tokens(system),
        "skill_advisory_tokens": section_tokens("ADVISORY_CONTEXT"),
        "manuscript_window_tokens": estimate_input_tokens(user),
        "rendered_message_tokens": estimate_input_tokens(rendered),
        "rendered_message_utf8_bytes": len(rendered.encode("utf-8")),
        "provider_wire_payload_utf8_bytes": len(wire_payload.encode("utf-8")),
        "provider_wire_payload_estimated_tokens": estimate_input_tokens(
            wire_payload
        ),
        "input_estimator_identity": "context_policy.estimate_input_tokens.v1",
        "protocol_overhead_tokens": 256,
        "rendered_message_sha256": rendered_message_sha256,
        "rendered_request_sha256": rendered_request_sha256,
        "destination_sha256": hashlib.sha256(
            destination.encode("utf-8"),
        ).hexdigest(),
        "request_shape_sha256": _domain({
            "protocol": protocol,
            "payload_keys": sorted(str(key) for key in payload),
            "role": role,
            "requested_output_tokens": maximum,
        }),
        "reasoning_field_present": "reasoning" in payload,
        "reasoning_effort": (
            (payload.get("reasoning") or {}).get("effort")
            if isinstance(payload.get("reasoning"), dict) else None
        ),
        "raw_prompt_persisted": False,
    }
    entry["input_envelope_sha256"] = _domain({
        key: entry[key] for key in (
            "route_fingerprint", "protocol", "role",
            "system_tokens", "task_tokens", "authority_context_tokens",
            "skill_advisory_tokens", "manuscript_window_tokens",
            "rendered_message_tokens",
            "rendered_message_utf8_bytes", "protocol_overhead_tokens",
            "rendered_request_sha256", "requested_output_tokens",
        )
    })
    return entry


def _quality_review() -> str:
    return json.dumps({
        "dimensions": {"commercial": 93, "story": 94, "prose": 92},
        "hard_fail": False, "decision": "pass", "issues": [],
    }, ensure_ascii=False)


class _PrivateDryRunOracle:
    """Deterministic response producer behind the lowest HTTP seam."""

    def __init__(
        self, *, inject_planning_business_incomplete_once: bool = False,
    ) -> None:
        self.base = DeterministicShortBoundary()
        self.inject_planning_business_incomplete_once = (
            inject_planning_business_incomplete_once
        )
        self.planning_business_incomplete_injected = False

    @staticmethod
    def _result(role: str, text: str) -> ModelResult:
        return ModelResult(text, {
            "role": role, "provider_id": "offline-memory",
            "model_id": "offline-memory-model",
            "model_name": f"offline-{role}", "finish_reason": "stop",
            "input_tokens": 2400, "output_tokens": 1200,
        })

    @staticmethod
    def _draft(user: str) -> str:
        contract = json.loads(
            user.split("CURRENT_TASK_CONTRACT:\n", 1)[1].split("\n\n", 1)[0]
        )
        target = max(600, int(contract.get("target_han") or 600))
        task_id = str(contract.get("task_id") or "segment-01")
        contract_identity = json.dumps(
            contract, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        )
        contract_digest = hashlib.sha256(
            contract_identity.encode("utf-8")
        ).hexdigest()
        task_variant = int(contract_digest[:8], 16)
        signature_alphabet = "零一二三四五六七八九甲乙丙丁戊己"
        task_signature = "".join(
            signature_alphabet[int(value, 16)] for value in contract_digest
        )
        segment_match = re.search(
            r"segment-(\d+)", task_id, re.IGNORECASE,
        )
        segment = int(segment_match.group(1)) if segment_match else 1
        actors = ("调查员", "档案员", "见证人", "审核员", "联络人", "保管员")
        places = ("档案室", "河堤仓库", "夜班车站", "听证室", "钟楼夹层")
        actions = ("核验签章", "比对时序", "追问见证", "封存副本", "公开底账")
        themes = (
            "雨水沿铜窗落下，蓝线目录把调查引向封存柜。",
            "河堤潮气改变纸张卷曲方向，搬运记录与口供发生冲突。",
            "夜班车站只亮着白灯，错位时刻表迫使众人重排见证顺序。",
            "听证室座次森严，公开质询让旧同盟无法掩盖账目缺口。",
            "钟楼夹层积着多年灰尘，新鞋印把怀疑推进为有限信任。",
            "晨光越过河面进入大厅，零散索引汇成可复核的完整底账。",
        )
        paragraphs: list[str] = []
        turn = 0
        while len("".join(paragraphs)) < target:
            actor = actors[(segment + task_variant + turn) % len(actors)]
            partner = actors[
                (segment + task_variant + turn + 2) % len(actors)
            ]
            place = places[
                (segment * 3 + task_variant + turn) % len(places)
            ]
            action = actions[
                (segment + task_variant + turn * 2) % len(actions)
            ]
            signature_offset = turn % len(task_signature)
            rotated_signature = (
                task_signature[signature_offset:]
                + task_signature[:signature_offset]
            )
            paragraphs.append(
                themes[(segment - 1 + task_variant) % len(themes)]
                + f"第{segment}段第{turn + 1}次核查发生在{place}。"
                + f"封签暗纹依次呈现{rotated_signature}。"
                f"{actor}围绕当前正式事件{action}，"
                f"在{partner}提出反证后重新排列时间、证物与知情边界；行动得到可复核结果，"
                "人物关系由戒备推进为有限合作，当前因果状态完整交给下一事件。"
            )
            turn += 1
        return "\n\n".join(paragraphs)

    @staticmethod
    def _hierarchy_receipt(user: str) -> str:
        source = re.search(r"SOURCE SHA256: ([0-9a-f]{64})", user)
        segments = re.search(r"EXPECTED SEGMENTS: (\[[^\n]+\])", user)
        events = re.search(r"EXPECTED EVENT IDS: (\[[^\n]+\])", user)
        if source is None or segments is None or events is None:
            raise AssertionError("hierarchy receipt authority is incomplete")
        return json.dumps({
            "source_sha256": source.group(1),
            "segment_numbers": json.loads(segments.group(1)),
            "event_ids": json.loads(events.group(1)),
            "causal_order_preserved": True,
            "adjacent_handoffs_preserved": True,
            "knowledge_progression_preserved": True,
            "relationship_progression_preserved": True,
            "viewpoint_timeline_preserved": True,
            "promises_ending_preserved": True,
            "formal_direction_preserved": True,
            "affected_segments": [], "affected_event_ids": [],
            "entry_state": "The accepted range starts from its bound entry.",
            "exit_state": "The accepted range hands off to its successor.",
            "knowledge_state": "Knowledge advances in formal event order.",
            "relationship_state": "Relationships advance through owned action.",
            "viewpoint_timeline": "Viewpoint and timeline remain bound.",
            "open_promises": [], "resolved_promises": [],
            "reason": "", "summary": "The complete range remains valid.",
        }, ensure_ascii=False)

    @staticmethod
    def _planning_event_realizations(user: str) -> str:
        event_ids = json.loads(
            user.split("EXPECTED EVENT IDS:\n", 1)[1].split("\n\n", 1)[0]
        )
        contracts = json.loads(
            user.split("FORMAL EVENT CONTRACTS:\n", 1)[1].split(
                "\n\nFORMAL EVENT COMPLETION CHECKLIST:", 1,
            )[0]
        )
        checklists = json.loads(
            user.split(
                "FORMAL EVENT COMPLETION CHECKLIST:\n", 1,
            )[1].split("\n\nPREVIOUS ACCEPTED HANDOFF:", 1)[0]
        )
        contract_by_id = {
            str(item.get("id") or "").upper(): item
            for item in contracts if isinstance(item, dict)
        }
        checklist_by_id = {
            str(item.get("event_id") or "").upper(): item
            for item in checklists if isinstance(item, dict)
        }
        events = []
        for event_id in event_ids:
            identity = str(event_id).upper()
            contract = contract_by_id.get(identity, {})
            checklist = checklist_by_id.get(identity, {})
            excerpts = [
                str(item.get("source_excerpt") or "").strip()
                for item in checklist.get("obligations", [])
                if isinstance(item, dict)
                and str(item.get("source_excerpt") or "").strip()
            ]
            narrative = " ".join(excerpts).strip()
            if not narrative:
                narrative = str(contract.get("evidence") or "").strip()
            narrative = (
                narrative
                + " 该事件依照正式合同保留既定执行者、动作、回应、结果、"
                "知情变化、关系推进、因果顺序和下一事件交接，不提前消费后续事件。"
            ).strip()
            if len(narrative) < 12:
                narrative = (
                    f"{contract.get('label') or identity}按正式事件合同完成行动、"
                    "回应与结果，并把既定状态交给下一事件。"
                )
            events.append({"event_id": identity, "narrative": narrative})
        return json.dumps({"events": events}, ensure_ascii=False)

    @staticmethod
    def _causal_chain(user: str) -> str:
        event_ids = list(dict.fromkeys(
            re.findall(r"EV-[0-9A-F]{8}", user.upper())
        ))
        return json.dumps({
            "core_goal": "调查员公开完整档案链并承担关系代价",
            "opening": {
                "pressure": "档案员失踪", "anomaly": "记录互相矛盾",
                "reader_question": "谁改写了档案",
                "future_promise": "底账将在天亮前公开",
            },
            "cycles": [{
                "obstacle": f"事件{index}的证据遭到阻拦",
                "effort": f"调查员核验事件{index}并争取证人",
                "result": f"事件{index}形成可复核结论",
                "state_change": f"人物知识与信任推进到状态{index}",
            } for index in range(1, max(2, len(event_ids) // 2) + 1)],
            "accidents": ["证人临时改口"],
            "reversal": {"content": "失踪者主动留下了矛盾索引"},
            "ending": {
                "surface_goal": "完整底账公开",
                "inner_goal": "调查员接受信任代价",
                "cost": "与旧同盟公开决裂",
            },
            "question_chain": [], "relationship_arc": [],
            "covered_event_ids": event_ids,
        }, ensure_ascii=False)

    @staticmethod
    def _causal_packet(user: str) -> str:
        contract = json.loads(
            user.split("PACKET CONTRACT:\n", 1)[1].splitlines()[0]
        )
        owned = [str(item).upper() for item in contract["owned_event_ids"]]
        owns_opening = user.split("OWNS OPENING: ", 1)[1].splitlines()[0] == "true"
        owns_ending = user.split("OWNS ENDING: ", 1)[1].splitlines()[0] == "true"
        return json.dumps({
            "core_goal": "公开完整底账" if owns_opening else "",
            "opening": {
                "pressure": "档案员失踪", "anomaly": "记录互相矛盾",
                "reader_question": "谁改写了档案",
                "future_promise": "底账将在天亮前公开",
            } if owns_opening else {},
            "cycles": [{
                "obstacle": f"{owned[0]}证据被阻拦",
                "effort": f"调查员核验{owned[0]}",
                "result": f"{owned[-1]}形成可复核结论",
                "state_change": f"知识推进到{owned[-1]}",
            }],
            "accidents": [], "reversal": {},
            "ending": {
                "surface_goal": "完整底账公开",
                "inner_goal": "接受关系代价", "cost": "与旧同盟决裂",
            } if owns_ending else "",
            "question_chain": [], "relationship_arc": [],
            "covered_event_ids": owned,
        }, ensure_ascii=False)

    @staticmethod
    def _whole_draft_receipt(user: str) -> str:
        if "WHOLE AUTHORITY INDEX: " in user:
            source = user.split("WHOLE AUTHORITY INDEX: ", 1)[1]
            index, _end = json.JSONDecoder().raw_decode(source)
            authority = str(index["authority_sha256"])
            draft_sha = str(index["draft_sha256"])
            segment_hashes = list(index["segment_sha256"])
            event_ids = list(index["event_ids"])
        else:
            authority = re.search(
                r"AUTHORITY SHA256: ([0-9a-f]{64})", user,
            ).group(1)
            draft_sha = re.search(
                r"DRAFT SHA256: ([0-9a-f]{64})", user,
            ).group(1)
            segment_hashes = json.loads(re.search(
                r"SEGMENT SHA256: (\[[^\n]+\])", user,
            ).group(1))
            event_ids = json.loads(re.search(
                r"EXPECTED EVENT IDS: (\[[^\n]+\])", user,
            ).group(1))
        opening = user.split("OPENING EXCERPT: ", 1)[1].split(
            "\nENDING EXCERPT:", 1,
        )[0]
        ending = user.split("ENDING EXCERPT: ", 1)[1]
        return json.dumps({
            "authority_sha256": authority, "draft_sha256": draft_sha,
            "segment_sha256": segment_hashes, "event_ids": event_ids,
            "missing_event_ids": [], "duplicate_event_ids": [],
            "out_of_order_event_ids": [], "causal_order_valid": True,
            "continuity_valid": True, "ending_valid": True,
            "commitments_valid": True,
            "evidence": [
                {"kind": "opening", "excerpt": opening[:20]},
                {"kind": "ending", "excerpt": ending[-20:]},
            ],
            "summary": "整篇正文保持事件顺序、连续性、承诺兑现与确认结局。",
        }, ensure_ascii=False)

    async def complete(
        self, role: str, system: str, user: str,
        max_output_tokens: int | None = None,
    ) -> ModelResult:
        if (
            self.inject_planning_business_incomplete_once
            and not self.planning_business_incomplete_injected
            and "ACTIONABLE_PLANNING_SEMANTIC_FINDINGS" not in user
            and any(marker in user for marker in (
                "IR_FIRST_SHORT_PLANNING_PACKET_V2",
                "IR_FIRST_SHORT_PLANNING_V2",
            ))
        ):
            complete = await self.base.complete(
                role, system, user, max_output_tokens=max_output_tokens,
            )
            payload = json.loads(complete.text)
            payload.pop("initial_state")
            self.planning_business_incomplete_injected = True
            return self._result(
                role, json.dumps(payload, ensure_ascii=False),
            )
        # The semantic-validation protocol names include the shorter fragment
        # generation marker.  Match the more-specific protocol first so the
        # fixture cannot misroute a validator request into the generator.
        if any(marker in user for marker in (
            "SHORT_EXECUTION_MANIFEST_SEMANTIC_VALIDATION",
            "SHORT_EXECUTION_MANIFEST_FRAGMENT_SEMANTIC_VALIDATION_V3",
            "SHORT_EXECUTION_MANIFEST_FRAGMENT_SEMANTIC_VALIDATION_V4",
        )):
            return self._result(role, _execution_manifest_receipt(user))
        if "DRAFT_WHOLE_SEMANTIC_VALIDATION" in user:
            return self._result(role, self._whole_draft_receipt(user))
        if "SHORT_INITIAL_REVIEW_WINDOW_V1" in user:
            return self._result(role, json.dumps({
                "summary": (
                    "This complete bounded window preserves ordered action, "
                    "knowledge changes, relationship movement, and its handoff."
                ),
                "issues": [],
            }))
        if "SHORT_INITIAL_REVIEW_REGIONAL_REDUCER_V1" in user:
            return self._result(role, json.dumps({
                "summary": (
                    "All covered initial-review windows remain ordered and "
                    "their source issue ledger is preserved."
                ),
                "issues": [],
            }))
        if "SHORT_READER_REVIEW_WINDOW_V1" in user:
            return self._result(role, json.dumps({
                "summary": (
                    "This complete target-reader window sustains reading "
                    "momentum, payoff expectation, and an explicit handoff."
                ),
                "issues": [],
            }))
        if "SHORT_READER_REVIEW_REGIONAL_REDUCER_V1" in user:
            return self._result(role, json.dumps({
                "summary": (
                    "All covered reader windows preserve their reading-state "
                    "handoffs and unresolved issue ledger."
                ),
                "issues": [],
            }))
        if "SHORT_READER_REVIEW_GLOBAL_REDUCER_V1" in user:
            payload = json.loads(_quality_review())
            payload["reader_signals"] = {
                "would_continue": True, "would_pay": True,
                "abandonment_point": "none", "payoff_felt": True,
            }
            return self._result(
                role, json.dumps(payload, ensure_ascii=False),
            )
        if "DRAFT_SEMANTIC_VALIDATION" in user:
            contract_match = re.search(r"TASK CONTRACT: (\{[^\n]+\})", user)
            if contract_match is None or "PROSE:\n" not in user:
                raise AssertionError("draft semantic authority is incomplete")
            contract = json.loads(contract_match.group(1))
            prose = user.split("PROSE:\n", 1)[1]
            return self._result(
                role,
                json.dumps(
                    _draft_semantic_receipt(contract, prose),
                    ensure_ascii=False,
                ),
            )
        if "SHORT_CAUSAL_CHAIN_STANDALONE" in user:
            return self._result(role, self._causal_chain(user))
        if "SHORT_CAUSAL_CHAIN_EVENT_PACKET_V2" in user:
            return self._result(role, self._causal_packet(user))
        if "SHORT_PLAN_EVENT_REALIZATION_REPAIR_V3" in user:
            return self._result(
                role, self._planning_event_realizations(user),
            )
        if any(marker in user for marker in (
            "SHORT_PLAN_ADAPTATION_REVIEW_V2",
            "SHORT_PLAN_ADAPTATION_WHOLE_STORY_REVIEW_V2",
        )):
            return await self.base.complete(
                role, system, user, max_output_tokens=max_output_tokens,
            )
        if (
            "SHORT_PLAN_ADAPTATION_REGIONAL_REVIEW_V3" in user
            or "SHORT_PLAN_ADAPTATION_HIERARCHY_REDUCTION_V3" in user
        ):
            return self._result(role, self._hierarchy_receipt(user))
        if role == "draft" and "DRAFT_SEMANTIC_VALIDATION" not in user:
            return self._result(role, self._draft(user))
        if role == "polish":
            return self._result(role, user.rsplit("MANUSCRIPT SEGMENT:\n", 1)[1])
        if role == "reader_review":
            payload = json.loads(_quality_review())
            payload["reader_signals"] = {
                "would_continue": True, "would_pay": True,
                "abandonment_point": "none", "payoff_felt": True,
            }
            return self._result(role, json.dumps(payload, ensure_ascii=False))
        if role == "review":
            return self._result(role, _quality_review())
        if role == "final_review" and "FULL MANUSCRIPT WINDOW SUMMARY" in user:
            return self._result(role, json.dumps({
                "summary": "Events, knowledge, relationships and timeline remain continuous.",
                "issues": [],
            }))
        if role == "final_review" and "终审详细事件和伏笔单独分析" in user:
            return self._result(role, json.dumps({
                "events": ["formal events complete"],
                "promises": ["the opening promise is paid off"],
                "character_states": ["knowledge advances monotonically"],
                "timeline": ["formal sequence is retained"],
            }))
        if role == "final_review" and "REGIONAL EVIDENCE REDUCTION" in user:
            return self._result(role, json.dumps({
                "summary": "Regional evidence remains continuous.", "issues": [],
            }))
        if role == "final_review":
            payload = json.loads(_quality_review())
            if "AUTHORITATIVE REVIEW ISSUE LEDGER:\n" in user:
                ledger = json.loads(user.split(
                    "AUTHORITATIVE REVIEW ISSUE LEDGER:\n", 1,
                )[1].split("\n\n", 1)[0])
                payload["reconciliations"] = [{
                    "issue_id": item["issue_id"], "status": "resolved",
                    "severity": item.get("severity", "medium"),
                    "evidence": "The exact accepted prose retains the event.",
                } for item in ledger]
            return self._result(role, json.dumps(payload, ensure_ascii=False))
        if "short_maintenance_business_complete_v2" in user:
            authority = json.loads(user)
            return self._result(role, json.dumps({
                "facts": [],
                "state": {},
                "coverage": {
                    "manuscript_sha256": authority[
                        "authoritative_manuscript"
                    ]["sha256"],
                    "complete": True,
                },
                "disposition": "no_change",
                "no_change_reason": (
                    "Complete manuscript inspection found no new durable "
                    "fact or character-state delta."
                ),
            }, ensure_ascii=False))
        if role == "maintenance":
            value = (
                {
                    "version": "maintenance-window-receipt-v1", "facts": [],
                    "state_deltas": [], "state_transitions": [],
                    "world_rules": [], "timeline": [],
                }
                if "maintenance-window-request-v1" in user else
                {
                    "facts": [], "state": {}, "state_transitions": [],
                    "world_rules": [], "timeline": [],
                }
            )
            return self._result(role, json.dumps(value, ensure_ascii=False))
        return await self.base.complete(
            role, system, user, max_output_tokens=max_output_tokens,
        )


class _OfflineHttpTransportFactory:
    """The only response stub: one in-memory ``httpx`` transport factory."""

    def __init__(
        self, *, inject_planning_business_incomplete_once: bool = False,
        inject_adapter_failure_after_exact_capture_once: bool = False,
        inject_planning_reasoning_only_once: bool = False,
    ) -> None:
        self.oracle = _PrivateDryRunOracle(
            inject_planning_business_incomplete_once=(
                inject_planning_business_incomplete_once
            ),
        )
        self.call_plan: list[dict[str, Any]] = []
        self.failure: dict[str, Any] | None = None
        self.registry_close_failure: Exception | None = None
        self.inject_adapter_failure_after_exact_capture_once = (
            inject_adapter_failure_after_exact_capture_once
        )
        self.adapter_failure_after_exact_capture_injected = False
        self.adapter_projection_call_count = 0
        self.inject_planning_reasoning_only_once = (
            inject_planning_reasoning_only_once
        )
        self.planning_reasoning_only_injected = False
        self.projected_reasoning_recovery_envelopes: list[dict[str, Any]] = []

    def install_adapter_failure_after_exact_capture_once(
        self, adapter: Any,
    ) -> None:
        """Inject one local projection fault without touching HTTP dispatch."""

        if (
            not self.inject_adapter_failure_after_exact_capture_once
            or self.adapter_failure_after_exact_capture_injected
            or not hasattr(adapter, "_model_response_from_body")
        ):
            return
        project = adapter._model_response_from_body

        def fail_once_after_capture(
            body: dict[str, Any], *, provider_state_extra: dict | None = None,
        ) -> Any:
            self.adapter_projection_call_count += 1
            if not self.adapter_failure_after_exact_capture_injected:
                self.adapter_failure_after_exact_capture_injected = True
                raise RuntimeError(
                    "injected local adapter failure after exact capture"
                )
            return project(
                body, provider_state_extra=provider_state_extra,
            )

        adapter._model_response_from_body = fail_once_after_capture

    def build(
        self, *, protocol: str, destination: str, bound_role: str | None = None,
        provider_id_sha256: str | None = None,
        model_id_sha256: str | None = None,
        model_name: str | None = None,
        route_fingerprint: str | None = None,
        provider_operator: str | None = None,
        route_lane: str | None = None,
    ) -> Any:
        async def respond(request: OfflineHttpRequestV1) -> OfflineHttpResponseV1:
            payload = json.loads(request.content.decode("utf-8"))
            system, user = _request_messages(payload)
            role = bound_role or _request_role(system, user)
            contract_marker = (
                "planning_semantic_v2"
                if any(marker in user for marker in (
                    "IR_FIRST_SHORT_PLANNING_PACKET_V2",
                    "IR_FIRST_SHORT_PLANNING_V2",
                ))
                else None
            )
            maximum = int(
                payload.get("max_tokens")
                or payload.get("max_output_tokens") or 0
            )
            self.call_plan.append(_safe_request_plan_entry_v1(
                ordinal=len(self.call_plan) + 1,
                protocol=protocol, destination=destination,
                provider_id_sha256=provider_id_sha256,
                model_id_sha256=model_id_sha256, model_name=model_name,
                route_fingerprint=route_fingerprint,
                provider_operator=provider_operator, route_lane=route_lane,
                role=role, contract_marker=contract_marker,
                maximum=maximum, payload=payload, system=system, user=user,
            ))
            if (
                self.inject_planning_reasoning_only_once
                and not self.planning_reasoning_only_injected
                and contract_marker == "planning_semantic_v2"
                and destination == "https://api.deepseek.com/anthropic"
                and "reasoning" not in payload
                and "ACTIONABLE_PLANNING_SEMANTIC_FINDINGS" not in user
                and (
                    not self.oracle.inject_planning_business_incomplete_once
                    or self.oracle.planning_business_incomplete_injected
                )
            ):
                self.planning_reasoning_only_injected = True
                recovery_payload = json.loads(json.dumps(payload))
                recovery_system = (
                    system + _FINAL_ARTIFACT_COMPLETION_SYSTEM_SUFFIX_V1
                )
                recovery_payload.pop("reasoning", None)
                if protocol == "anthropic":
                    recovery_payload["system"] = recovery_system
                elif protocol == "openai-responses":
                    recovery_payload["instructions"] = recovery_system
                else:
                    messages = list(recovery_payload.get("messages") or [])
                    replaced = False
                    for item in messages:
                        if isinstance(item, dict) and item.get("role") == "system":
                            item["content"] = recovery_system
                            replaced = True
                            break
                    if not replaced:
                        messages.insert(0, {
                            "role": "system", "content": recovery_system,
                        })
                    recovery_payload["messages"] = messages
                projected = _safe_request_plan_entry_v1(
                    ordinal=len(self.call_plan) + 1,
                    protocol=protocol, destination=destination,
                    provider_id_sha256=provider_id_sha256,
                    model_id_sha256=model_id_sha256, model_name=model_name,
                    route_fingerprint=route_fingerprint,
                    provider_operator=provider_operator,
                    route_lane=route_lane, role=role,
                    contract_marker=contract_marker, maximum=maximum,
                    payload=recovery_payload, system=recovery_system,
                    user=user,
                )
                projected.update({
                    "attempt_role": "PLANNING_FINAL_ARTIFACT_RECOVERY",
                    "recovery_overlay_kind": "FINAL_ARTIFACT_COMPLETION",
                    "projection_status": (
                        "DETERMINISTIC_CONTRACT_RUNTIME_PROJECTION_"
                        "NOT_DISPATCHED"
                    ),
                })
                self.projected_reasoning_recovery_envelopes.append(projected)
                return OfflineHttpResponseV1(200, json_body={
                    "id": "offline-reasoning-only",
                    "content": [{
                        "type": "thinking",
                        "thinking": "offline deterministic hidden-work fixture",
                        "signature": "offline-signature",
                    }],
                    "stop_reason": "max_tokens",
                    "usage": {
                        "input_tokens": 2400,
                        "output_tokens": maximum,
                    },
                })
            try:
                result = await self.oracle.complete(
                    role, system, user, max_output_tokens=maximum,
                )
            except Exception as exc:
                # Retain only bounded protocol diagnostics; never retain the
                # prompt or response that crossed the mocked HTTP seam.
                self.failure = {
                    "ordinal": len(self.call_plan), "role": role,
                    **_safe_failure_projection(
                        exc, boundary="offline_http_transport.oracle",
                    ),
                    "known_protocol_markers": [
                        marker for marker in (
                            "SHORT_PLAN_ADAPTATION_REVIEW_V2",
                            "SHORT_PLAN_ADAPTATION_WHOLE_STORY_REVIEW_V2",
                            "SHORT_CAUSAL_CHAIN_STANDALONE",
                            "SHORT_CAUSAL_CHAIN_EVENT_PACKET_V2",
                            "SHORT_EXECUTION_MANIFEST_V2",
                            "SHORT_EXECUTION_MANIFEST_FRAGMENT_V3",
                            "SHORT_EXECUTION_MANIFEST_FRAGMENT_V4",
                            "SHORT_EXECUTION_MANIFEST_SEMANTIC_VALIDATION",
                            "SHORT_EXECUTION_MANIFEST_FRAGMENT_SEMANTIC_VALIDATION_V3",
                            "SHORT_EXECUTION_MANIFEST_FRAGMENT_SEMANTIC_VALIDATION_V4",
                            "DRAFT_SEMANTIC_VALIDATION",
                            "DRAFT_WHOLE_SEMANTIC_VALIDATION",
                            "CURRENT_TASK_CONTRACT",
                        ) if marker in user
                    ],
                }
                raise
            if protocol == "openai-chat":
                body = {
                    "id": "offline", "choices": [{
                        "message": {"role": "assistant", "content": result.text},
                        "finish_reason": "stop",
                    }],
                    "usage": {"prompt_tokens": 2400, "completion_tokens": 1200},
                }
            elif protocol == "openai-responses":
                body = {
                    "id": "offline", "status": "completed",
                    "output": [{"type": "message", "role": "assistant",
                                "content": [{"type": "output_text", "text": result.text}]}],
                    "usage": {"input_tokens": 2400, "output_tokens": 1200},
                }
            else:
                body = {
                    "id": "offline", "content": [{"type": "text", "text": result.text}],
                    "stop_reason": "end_turn",
                    "usage": {"input_tokens": 2400, "output_tokens": 1200},
                }
            return OfflineHttpResponseV1(200, json_body=body)

        return build_offline_http_transport_v1(respond)


class _CapturedResponseReplayTransportFactory:
    """Feed ledger-anchored captured bytes back through real adapters."""

    def __init__(
        self, *, capture_store: ProviderResponseCaptureStoreV1,
        ledger: dict[str, Any], source_call_plan: list[dict[str, Any]],
    ) -> None:
        self.capture_store = capture_store
        self.ledger = ledger
        self.source_call_plan = source_call_plan
        self.call_plan: list[dict[str, Any]] = []
        self.failure: dict[str, Any] | None = None
        audited = capture_store.audit_all(
            expected_receipt_sha256s=_capture_receipt_anchors_from_ledger(
                ledger,
            ),
        )
        self._captures = {
            (str(item["call_id"]), str(item["byte_domain"])): item
            for item in audited
        }

    def build(
        self, *, protocol: str, destination: str, bound_role: str | None = None,
        provider_id_sha256: str | None = None,
        model_id_sha256: str | None = None,
        model_name: str | None = None,
        route_fingerprint: str | None = None,
        provider_operator: str | None = None,
        route_lane: str | None = None,
    ) -> Any:
        async def respond(request: OfflineHttpRequestV1) -> OfflineHttpResponseV1:
            ordinal = len(self.call_plan) + 1
            if ordinal > len(self.ledger["attempts"]):
                raise RuntimeError("FULL_SHORT_CAPTURE_REPLAY_EXTRA_DISPATCH")
            attempt = self.ledger["attempts"][ordinal - 1]
            source = self.source_call_plan[ordinal - 1]
            payload = json.loads(request.content.decode("utf-8"))
            system, user = _request_messages(payload)
            role = bound_role or _request_role(system, user)
            maximum = int(
                payload.get("max_tokens")
                or payload.get("max_output_tokens") or 0
            )
            observed = _safe_request_plan_entry_v1(
                ordinal=ordinal, protocol=protocol, destination=destination,
                provider_id_sha256=provider_id_sha256,
                model_id_sha256=model_id_sha256, model_name=model_name,
                route_fingerprint=route_fingerprint,
                provider_operator=provider_operator, route_lane=route_lane,
                role=role,
                contract_marker=(
                    "planning_semantic_v2"
                    if any(marker in user for marker in (
                        "IR_FIRST_SHORT_PLANNING_PACKET_V2",
                        "IR_FIRST_SHORT_PLANNING_V2",
                    )) else None
                ),
                maximum=maximum, payload=payload, system=system, user=user,
            )
            if observed != source:
                differing_fields = {
                    key: {
                        "expected_sha256": _domain(source.get(key)),
                        "observed_sha256": _domain(observed.get(key)),
                    }
                    for key in sorted(set(source) | set(observed))
                    if source.get(key) != observed.get(key)
                }
                self.failure = {
                    "reason_code": "FULL_SHORT_CAPTURE_REPLAY_REQUEST_DRIFT",
                    "ordinal": ordinal,
                    "expected_sha256": _domain(source),
                    "observed_sha256": _domain(observed),
                    "differing_fields": differing_fields,
                }
                raise RuntimeError("FULL_SHORT_CAPTURE_REPLAY_REQUEST_DRIFT")
            self.call_plan.append(observed)
            call_id = f"{self.ledger['execution_id']}:{attempt['ordinal']}"
            capture = self._captures.get(
                (call_id, PROVIDER_PROTOCOL_INPUT_BYTES),
            )
            if capture is None:
                raise RuntimeError("FULL_SHORT_CAPTURE_REPLAY_RAW_MISSING")
            data, header = self.capture_store.replay(
                byte_domain=PROVIDER_PROTOCOL_INPUT_BYTES,
                expected_metadata=capture["metadata"],
                expected_receipt_sha256=attempt[
                    "provider_protocol_capture_receipt_sha256"
                ],
            )
            return OfflineHttpResponseV1(
                200, content=data,
                headers={"content-type": str(header["content_type"])},
            )

        return build_offline_http_transport_v1(respond)


class _DiagnosticObserverProxy:
    """Forward the real observer while retaining only typed failure metadata."""

    def __init__(
        self, target: Any, factory: _OfflineHttpTransportFactory,
    ) -> None:
        self._target = target
        self._factory = factory

    def __getattr__(self, name: str) -> Any:
        attribute = getattr(self._target, name)
        if not callable(attribute):
            return attribute

        def call(*args: Any, **kwargs: Any) -> Any:
            try:
                return attribute(*args, **kwargs)
            except Exception as exc:
                envelope = getattr(exc, "envelope", None)
                self._factory.failure = {
                    "boundary": f"attempt_observer.{name}",
                    **_safe_failure_projection(
                        exc, boundary=f"attempt_observer.{name}",
                    ),
                    "reason_code": getattr(exc, "reason_code", None),
                    "runtime_boundary_id": getattr(
                        envelope, "boundary_id", None,
                    ),
                    "runtime_failure_code": getattr(
                        envelope, "failure_code", None,
                    ),
                    "runtime_source_exception_class": getattr(
                        envelope, "source_exception_class", None,
                    ),
                    "runtime_source_reason_code": getattr(
                        envelope, "source_reason_code", None,
                    ),
                    "runtime_state": str(getattr(
                        envelope, "current_state", "",
                    )) or None,
                }
                raise

        return call


class _LogicalStagePlanDiscoveryObserver:
    """Collect the credential-free ordered logical plan during dry discovery."""

    def __init__(self) -> None:
        self.logical_stage_plan: list[dict[str, Any]] = []
        self.pending: dict[str, Any] | None = None
        self.bound_route: dict[str, Any] | None = None

    def bind_stage_context(self, **value: Any) -> None:
        stage_id = str(value["stage_id"])
        contract_attempt_index = value.get("contract_attempt_index")
        prior_stage_attempts = [
            item for item in self.logical_stage_plan
            if item["logical_stage_base_id"] == stage_id
        ]
        if (
            type(contract_attempt_index) is int
            and contract_attempt_index > 1
            and prior_stage_attempts
        ):
            logical_stage_id = prior_stage_attempts[-1]["logical_stage_id"]
        else:
            occurrence = 1 + sum(
                item["logical_stage_base_id"] == stage_id
                and (
                    item.get("contract_attempt_index") in {None, 1}
                )
                for item in self.logical_stage_plan
            )
            logical_stage_id = full_short_logical_stage_id_v1(
                stage_id, occurrence,
            )
        self.pending = {
            "stage_id": stage_id,
            "logical_stage_base_id": stage_id,
            "logical_stage_id": logical_stage_id,
            "contract_name": str(value["contract_name"]),
            "contract_version": int(value["contract_version"]),
            "contract_schema_sha256": str(value["contract_schema_sha256"]),
            "contract_runtime_input_required": bool(
                value.get("contract_runtime_input_required")
            ),
            "contract_attempt_index": contract_attempt_index,
            "contract_route": value.get("contract_route"),
            "contract_route_attempt": value.get("contract_route_attempt"),
            "stage_role": str(value.get("stage_role") or "NORMAL"),
        }

    def bind_route(
        self, *, role: str, lane: str, provider_id: str, model_id: str,
        route_fingerprint: str,
    ) -> None:
        self.bound_route = {
            "role": role, "lane": lane,
            "role_binding_sha256": _domain({
                "role": role, "lane": lane,
                "provider_id_sha256": hashlib.sha256(
                    provider_id.encode("utf-8")
                ).hexdigest(),
                "model_id_sha256": hashlib.sha256(
                    model_id.encode("utf-8")
                ).hexdigest(),
                "route_fingerprint": route_fingerprint,
            }),
        }

    def bind_model_request(self, *, protocol: str, request: Any) -> None:
        if self.pending is None:
            if self.bound_route is None:
                raise RuntimeError("FULL_SHORT_DISCOVERY_STAGE_CONTEXT_MISSING")
            response_schema = request.response_schema or {}
            schema_value = response_schema.get("schema", response_schema)
            stage_id = str(self.bound_route["role"] or "model")
            occurrence = 1 + sum(
                item["logical_stage_base_id"] == stage_id
                for item in self.logical_stage_plan
            )
            self.pending = {
                "stage_id": stage_id,
                "logical_stage_base_id": stage_id,
                "logical_stage_id": full_short_logical_stage_id_v1(
                    stage_id, occurrence,
                ),
                "contract_name": str(
                    response_schema.get("name") or "unstructured_text"
                ),
                "contract_version": 1,
                "contract_schema_sha256": _domain(schema_value),
                "contract_runtime_input_required": bool(response_schema),
                "contract_attempt_index": None,
                "contract_route": None,
                "contract_route_attempt": None,
                "stage_role": "NORMAL",
            }
        self.pending["requested_output_tokens"] = int(
            request.max_output_tokens or 8192
        )

    def before_http_dispatch(self, **_value: Any) -> None:
        if self.pending is None or self.bound_route is None:
            raise RuntimeError("FULL_SHORT_DISCOVERY_PLAN_BINDING_MISSING")
        self.logical_stage_plan.append({
            "ordinal": len(self.logical_stage_plan) + 1,
            **self.pending,
            "role": self.bound_route["role"],
            "route_lane": (
                "configured_fallback"
                if self.bound_route["lane"] == "fallback"
                else self.bound_route["lane"]
            ),
        })

    def before_http_post(self) -> None:
        return None

    def before_network_request(self) -> None:
        return None

    def after_http_response(self, **_value: Any) -> None:
        return None

    def after_http_failure(self, **_value: Any) -> None:
        return None

    def capture_provider_protocol_input(self, **_value: Any) -> None:
        return None

    def capture_contract_runtime_input(self, **_value: Any) -> None:
        return None

    def mark_local_stage_complete(self, **_value: Any) -> None:
        self.pending = None
        self.bound_route = None


class _LowestHttpSeamRegistry(ProviderRegistry):
    """Real resolver/adapters with only their HTTP client transport replaced."""

    def __init__(
        self, *args: Any,
        http_transport_factory: Any | None = None,
        **kwargs: Any,
    ) -> None:
        if http_transport_factory is None:
            raise ValueError("offline HTTP transport factory is required")
        self.transport_factory = http_transport_factory
        observer = kwargs.get("attempt_observer")
        if observer is None:
            observer = _LogicalStagePlanDiscoveryObserver()
            kwargs["attempt_observer"] = observer
        self.logical_stage_plan_observer = observer
        if observer is not None:
            kwargs["attempt_observer"] = _DiagnosticObserverProxy(
                observer, http_transport_factory,
            )
        super().__init__(*args, **kwargs)
        self.open_clients: list[Any] = []

    def _install_optional_adapter_failure_hook(self, adapter: Any) -> None:
        hook = getattr(
            self.transport_factory,
            "install_adapter_failure_after_exact_capture_once",
            None,
        )
        if callable(hook):
            hook(adapter)

    @property
    def call_plan(self) -> list[dict[str, Any]]:
        return self.transport_factory.call_plan

    @property
    def observed_roles(self) -> list[str]:
        return [str(item["role"]) for item in self.call_plan]

    def resolve(
        self, provider_id: str, model_id: str, *,
        role: str | None = None, lane: str | None = None,
    ):
        public = self.inspect_public_route(provider_id, model_id)
        provider = public.provider
        model = public.model
        protocol = public.protocol
        destination = str(provider.get("base_url") or "").rstrip("/")
        try:
            bind_route = getattr(self.attempt_observer, "bind_route", None)
            if callable(bind_route):
                bind_route(
                    role=str(role or ""), lane=str(lane or ""),
                    provider_id=provider_id, model_id=model_id,
                    route_fingerprint=public.route_fingerprint,
                )
            secret = self.secrets.get(provider_id)
            if not secret:
                raise ValueError("offline memory secret is missing")
            transport = self.transport_factory.build(
                protocol=protocol, destination=destination, bound_role=role,
                provider_id_sha256=hashlib.sha256(
                    provider_id.encode("utf-8")
                ).hexdigest(),
                model_id_sha256=hashlib.sha256(
                    model_id.encode("utf-8")
                ).hexdigest(),
                model_name=str(model.get("model_name") or ""),
                route_fingerprint=public.route_fingerprint,
                provider_operator=public.provider_operator,
                route_lane=str(lane or ""),
            )
            if type(transport) is not httpx.MockTransport:
                raise ValueError("OFFLINE_HTTP_TRANSPORT_NOT_CLOSED")
            adapter = ADAPTERS[protocol](
                provider["base_url"], secret, provider["extra_headers"],
                provider["timeout_seconds"], auth_type=provider["auth_type"],
                transport_policy=self.transport_policy,
                attempt_observer=self.attempt_observer,
                injected_http_transport=transport,
            )
            resolved = ResolvedModel(
                provider_id, model_id, model["model_name"], adapter,
                self._effective_capabilities(
                    model.get("capabilities") or {}, public.route_fingerprint,
                ),
                public.route_fingerprint,
                provider_operator=public.provider_operator,
                protocol=public.protocol,
                destination=public.destination,
                route_lane=str(lane or ""),
            )
        except Exception as exc:
            self.transport_factory.failure = {
                "boundary": "provider_registry.resolve",
                **_safe_failure_projection(
                    exc, boundary="provider_registry.resolve",
                ),
                "reason_code": getattr(exc, "reason_code", None),
                "attempted_role": str(role or ""),
                "attempted_lane": str(lane or ""),
                "attempted_provider_id_sha256": hashlib.sha256(
                    provider_id.encode("utf-8")
                ).hexdigest(),
                "attempted_model_id_sha256": hashlib.sha256(
                    model_id.encode("utf-8")
                ).hexdigest(),
            }
            raise
        self.transport_factory.failure = None
        self._install_optional_adapter_failure_hook(resolved.adapter)
        self.open_clients.append(resolved.adapter.client)
        return resolved

    async def close(self) -> None:
        clients = tuple(self.open_clients)
        self.open_clients.clear()
        errors: list[Exception] = []
        for client in clients:
            try:
                await client.aclose()
            except Exception as exc:
                errors.append(exc)
        if errors:
            close_error = ExceptionGroup(
                "FULL_SHORT_OFFLINE_REGISTRY_CLOSE_FAILED", errors,
            )
            self.transport_factory.registry_close_failure = close_error
            raise close_error


def _registry_factory(*args: Any, **kwargs: Any) -> _LowestHttpSeamRegistry:
    return _LowestHttpSeamRegistry(*args, **kwargs)


def _full_short_bound_models_v1(
    db: Database,
) -> tuple[tuple[str, str], ...]:
    """Return the distinct provider/model pairs reachable by Full Short."""

    bound: dict[str, str] = {}
    for role in FULL_SHORT_BOUND_ROLES:
        binding = db.get_role_binding(role) or {}
        if role in FULL_SHORT_REQUIRED_EXECUTION_ROLES and not (
            binding.get("primary_provider_id")
            and binding.get("primary_model_id")
        ):
            raise ValueError(
                "offline context manifest required route is missing"
            )
        for lane in ("primary", "fallback"):
            provider_id = binding.get(f"{lane}_provider_id")
            model_id = binding.get(f"{lane}_model_id")
            if not provider_id and not model_id:
                continue
            if not provider_id or not model_id:
                raise ValueError(
                    "offline context manifest route binding is incomplete"
                )
            previous = bound.setdefault(str(model_id), str(provider_id))
            if previous != str(provider_id):
                raise ValueError(
                    "offline context manifest model provider is ambiguous"
                )
    return tuple(sorted(
        (provider_id, model_id) for model_id, provider_id in bound.items()
    ))


def _validate_offline_gateway_context_manifest_v1(db: Database) -> None:
    """Fail closed unless every bound private model has the exact manifest."""

    for provider_id, model_id in _full_short_bound_models_v1(db):
        model = db.get_model(model_id)
        if model is None or str(model.get("provider_id")) != provider_id:
            raise ValueError(
                "offline context manifest bound model is unavailable"
            )
        if model.get("context_window") != OFFLINE_CONTEXT_LIMIT_TOKENS_V1:
            raise ValueError(
                "offline context manifest model context limit mismatch"
            )
        capabilities = model.get("capabilities")
        if not isinstance(capabilities, dict):
            raise ValueError(
                "offline context manifest capabilities are invalid"
            )
        marker = capabilities.get(OFFLINE_CONTEXT_MANIFEST_KEY_V1)
        if marker != OFFLINE_CONTEXT_MANIFEST_V1:
            raise ValueError(
                "offline context manifest marker mismatch"
            )


def _install_offline_gateway_context_manifest_v1(db: Database) -> None:
    """Install the deterministic gateway capacity source in a private DB."""

    updates: list[tuple[str, str]] = []
    for provider_id, model_id in _full_short_bound_models_v1(db):
        model = db.get_model(model_id)
        if model is None or str(model.get("provider_id")) != provider_id:
            raise ValueError(
                "offline context manifest bound model is unavailable"
            )
        capabilities = model.get("capabilities")
        if not isinstance(capabilities, dict):
            raise ValueError(
                "offline context manifest capabilities are invalid"
            )
        private_capabilities = dict(capabilities)
        private_capabilities[OFFLINE_CONTEXT_MANIFEST_KEY_V1] = dict(
            OFFLINE_CONTEXT_MANIFEST_V1
        )
        updates.append((
            json.dumps(
                private_capabilities,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            model_id,
        ))
    with db.connect() as connection:
        for capabilities_json, model_id in updates:
            connection.execute(
                """UPDATE models
                SET context_window=?, capabilities_json=? WHERE id=?""",
                (
                    OFFLINE_CONTEXT_LIMIT_TOKENS_V1,
                    capabilities_json,
                    model_id,
                ),
            )
    _validate_offline_gateway_context_manifest_v1(db)


def _copy_private_data(
    *, repo: Path, source_project: Path, project_id: str, target: Path,
    install_offline_gateway_context_manifest: bool = False,
    private_role_binding_overrides: tuple[
        tuple[str, str, str, str | None, str | None], ...
    ] = (),
) -> Path:
    data = target / "data"
    projects_root = data / "projects"
    projects_root.mkdir(parents=True)
    shutil.copy2(repo / "data" / "app.db", data / "app.db")
    private_project = projects_root / source_project.name
    shutil.copytree(source_project, private_project)
    source_references = (repo / "data" / "references").resolve()
    private_references = data / "references"
    if source_references.is_dir():
        shutil.copytree(source_references, private_references)
    else:
        private_references.mkdir()
    db = Database(data / "app.db")
    for row in db.list_projects():
        private_path = projects_root / f"unselected-{row['id']}"
        if str(row["id"]) == project_id:
            private_path = private_project
        db.update_project_path(str(row["id"]), private_path)
    with db.connect() as connection:
        versions = connection.execute(
            "SELECT id,storage_path FROM reference_versions ORDER BY id",
        ).fetchall()
        for version in versions:
            source_path = Path(str(version["storage_path"])).resolve()
            try:
                relative = source_path.relative_to(source_references)
            except ValueError as exc:
                raise ValueError(
                    "reference source escapes the live storage root"
                ) from exc
            private_path = private_references / relative
            if not private_path.is_file():
                raise ValueError("reference source is missing from private copy")
            connection.execute(
                "UPDATE reference_versions SET storage_path=? WHERE id=?",
                (str(private_path), str(version["id"])),
            )
    ProjectStore(db, projects_root).get(project_id)
    # Authority closure is enabled only in the isolated copies.  The live
    # project remains untouched and must be separately enabled before a real
    # authorization can pass.
    db.set_feature_flag(
        "short_canonical_v2", True,
        scope_type="project", scope_id=project_id,
    )
    for binding_override in private_role_binding_overrides:
        db.save_role_binding(*binding_override)
    if install_offline_gateway_context_manifest:
        _install_offline_gateway_context_manifest_v1(db)
    return data


def _memory_secrets(data_dir: Path) -> Callable[[], MemorySecretStore]:
    provider_ids = [
        str(item["id"]) for item in Database(data_dir / "app.db").list_providers()
    ]

    def create() -> MemorySecretStore:
        store = MemorySecretStore()
        for provider_id in provider_ids:
            store.set(provider_id, "offline-memory-only-secret")
        return store

    return create


async def _discover_plan(
    *, repo: Path, data_dir: Path, project_id: str,
    inject_planning_business_incomplete_once: bool = False,
    inject_planning_reasoning_only_once: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    factory = _OfflineHttpTransportFactory(
        inject_planning_business_incomplete_once=(
            inject_planning_business_incomplete_once
        ),
        inject_planning_reasoning_only_once=(
            inject_planning_reasoning_only_once
        ),
    )
    db = Database(data_dir / "app.db")
    registry = _LowestHttpSeamRegistry(
        db, _memory_secrets(data_dir)(),
        http_transport_factory=factory,
        transport_policy=SingleDispatchTransportPolicyV1.phase_b(),
    )
    _db, _project, result = await _await_with_registry_close(
        lambda: run_full_short_workflow_path(
            repo=repo, data_dir=data_dir, project_id=project_id,
            execution_id=DISCOVERY_ID, registry=registry,
        ),
        registry,
    )
    if result.get("status") != "completed":
        failure = {
            key: result.get(key)
            for key in ("status", "current_stage", "error")
        }
        failure["mock_transport_failure"] = factory.failure
        failure["observed_call_count"] = len(factory.call_plan)
        failure["observed_call_tail"] = factory.call_plan[-5:]
        project_row = db.get_project(project_id) or {}
        project_root = Path(str(project_row.get("path") or ""))
        outputs = project_root / "runs" / DISCOVERY_ID / "outputs"
        failure["output_file_names"] = sorted(
            item.name for item in outputs.glob("*") if item.is_file()
        )[-40:]
        failure["run_event_tail"] = [
            {
                "severity": item.get("severity"),
                "event_type": item.get("event_type"),
                "stage": item.get("stage"),
                "message_sha256": _optional_text_sha256(item.get("message")),
                "metadata_keys": sorted(
                    str(key) for key in (item.get("metadata") or {})
                ),
                "error_type": (item.get("metadata") or {}).get("error_type"),
                "failure_code": (item.get("metadata") or {}).get(
                    "failure_code"
                ),
            }
            for item in db.list_run_events(DISCOVERY_ID)[-12:]
        ]
        raise RuntimeError(
            "FULL_SHORT_DRY_RUN_PLAN_DID_NOT_COMPLETE:"
            + json.dumps(failure, ensure_ascii=True, sort_keys=True)
        )
    missing = sorted(
        set(FULL_SHORT_REQUIRED_EXECUTION_ROLES) - set(registry.observed_roles)
    )
    if missing:
        raise RuntimeError("FULL_SHORT_DRY_RUN_PLAN_MISSING_REQUIRED_ROLE")
    if not registry.call_plan:
        raise RuntimeError("FULL_SHORT_DRY_RUN_PLAN_EMPTY")
    logical_stage_plan = list(
        registry.logical_stage_plan_observer.logical_stage_plan
    )
    if len(logical_stage_plan) != len(registry.call_plan):
        raise RuntimeError("FULL_SHORT_DRY_RUN_LOGICAL_PLAN_INCOMPLETE")
    return registry.call_plan, logical_stage_plan


async def _discover_reasoning_recovery_projection_v1(
    *, repo: Path, data_dir: Path, project_id: str,
) -> dict[str, Any]:
    """Render the sealed Planning final-artifact retry without dispatching it."""

    factory = _OfflineHttpTransportFactory(
        inject_planning_reasoning_only_once=True,
    )
    registry = _LowestHttpSeamRegistry(
        Database(data_dir / "app.db"), _memory_secrets(data_dir)(),
        http_transport_factory=factory,
        transport_policy=SingleDispatchTransportPolicyV1.phase_b(),
    )
    try:
        await _await_with_registry_close(
            lambda: run_full_short_workflow_path(
                repo=repo, data_dir=data_dir, project_id=project_id,
                execution_id=DISCOVERY_ID, registry=registry,
            ),
            registry,
        )
    except Exception:
        # The ordinary discovery observer owns one route slot, so the typed
        # reasoning-only response terminates locally.  The exact sealed retry
        # payload was already projected from the in-memory request above.
        pass
    projections = list(factory.projected_reasoning_recovery_envelopes)
    if len(projections) != 1:
        raise RuntimeError(
            "FULL_SHORT_REASONING_RECOVERY_PROJECTION_INCOMPLETE"
        )
    return projections[0]


def _replayed_adapter_text(
    *, protocol: str, events: list[dict[str, Any]],
    body: dict[str, Any] | None,
) -> str:
    """Project replayed protocol objects through the production text seam."""

    if protocol == "anthropic":
        blocks = (
            list(body.get("content") or []) if body is not None
            else [event.get("delta") or {} for event in events]
        )
        return "".join(
            str(block.get("text") or "")
            for block in blocks
            if isinstance(block, dict)
        )
    if protocol == "openai-chat":
        if body is not None:
            choices = list(body.get("choices") or [])
            return "".join(
                str((choice.get("message") or {}).get("content") or "")
                for choice in choices if isinstance(choice, dict)
            )
        return "".join(
            str((event.get("choices") or [{}])[0].get("delta", {}).get(
                "content", ""
            ))
            for event in events if isinstance(event, dict)
            and event.get("choices")
        )
    if protocol == "openai-responses":
        source = list(body.get("output") or []) if body is not None else events
        texts: list[str] = []
        for item in source:
            if not isinstance(item, dict):
                continue
            if item.get("type") in {"response.output_text.delta", "output_text"}:
                texts.append(str(item.get("delta") or item.get("text") or ""))
            for content in item.get("content") or []:
                if isinstance(content, dict):
                    texts.append(str(content.get("text") or ""))
        return "".join(texts)
    raise RuntimeError("FULL_SHORT_CAPTURE_REPLAY_PROTOCOL_UNSUPPORTED")


def _attempt_requires_contract_runtime_capture_v1(
    attempt: dict[str, Any],
) -> bool:
    """Mirror the durable pre-contract final-artifact rejection boundary."""

    return bool(attempt.get("contract_runtime_input_required")) and (
        attempt.get("local_rejection_schema")
        != "ProviderFinalArtifactRejectionReceiptV1"
    )


def _capture_receipt_anchors_from_ledger(
    ledger: Mapping[str, Any],
) -> list[str]:
    """Return the exact external capture anchors recorded by the ledger."""

    anchors: list[str] = []
    for attempt in ledger.get("attempts") or ():
        if not isinstance(attempt, Mapping):
            continue
        for field in (
            "provider_protocol_capture_receipt_sha256",
            "contract_runtime_capture_receipt_sha256",
        ):
            value = attempt.get(field)
            if value is not None:
                anchors.append(str(value))
    return anchors


def _replay_captured_attempts(
    *, capture_store: ProviderResponseCaptureStoreV1, ledger: dict[str, Any],
) -> dict[str, Any]:
    """Replay every capture against its ledger anchor and conversion contract."""

    audited = capture_store.audit_all(
        expected_receipt_sha256s=_capture_receipt_anchors_from_ledger(ledger),
    )
    indexed = {
        (str(item["call_id"]), str(item["byte_domain"])): item
        for item in audited
    }
    if len(indexed) != len(audited):
        raise RuntimeError("FULL_SHORT_CAPTURE_REPLAY_DUPLICATE_IDENTITY")
    replayed_domains = 0
    converted_contracts = 0
    business_rejections = 0
    for attempt in ledger["attempts"]:
        call_id = f"{ledger['execution_id']}:{attempt['ordinal']}"
        raw_receipt = indexed.get((call_id, PROVIDER_PROTOCOL_INPUT_BYTES))
        if raw_receipt is None:
            raise RuntimeError("FULL_SHORT_CAPTURE_REPLAY_RAW_MISSING")
        if raw_receipt["ledger_receipt_sha256"] != attempt.get(
            "provider_protocol_capture_receipt_sha256"
        ):
            raise RuntimeError("FULL_SHORT_CAPTURE_REPLAY_RAW_LEDGER_DRIFT")
        raw, raw_header = capture_store.replay(
            byte_domain=PROVIDER_PROTOCOL_INPUT_BYTES,
            expected_metadata=raw_receipt["metadata"],
            expected_receipt_sha256=attempt[
                "provider_protocol_capture_receipt_sha256"
            ],
        )
        events, body = parse_provider_protocol_input_bytes_v1(
            raw, content_type=str(raw_header["content_type"]),
            encoding=str(raw_header["encoding"]),
        )
        replayed_domains += 1
        if not _attempt_requires_contract_runtime_capture_v1(attempt):
            continue
        contract_receipt = indexed.get((call_id, CONTRACT_RUNTIME_INPUT_BYTES))
        if contract_receipt is None:
            raise RuntimeError("FULL_SHORT_CAPTURE_REPLAY_CONTRACT_MISSING")
        if contract_receipt["ledger_receipt_sha256"] != attempt.get(
            "contract_runtime_capture_receipt_sha256"
        ):
            raise RuntimeError("FULL_SHORT_CAPTURE_REPLAY_CONTRACT_LEDGER_DRIFT")
        contract_bytes, _contract_header = capture_store.replay(
            byte_domain=CONTRACT_RUNTIME_INPUT_BYTES,
            expected_metadata=contract_receipt["metadata"],
            expected_receipt_sha256=attempt[
                "contract_runtime_capture_receipt_sha256"
            ],
        )
        try:
            contract_text = contract_bytes.decode("utf-8")
        except UnicodeError as exc:
            raise RuntimeError("FULL_SHORT_CAPTURE_REPLAY_CONTRACT_UTF8_INVALID") from exc
        replayed_text = _replayed_adapter_text(
            protocol=str(raw_header["protocol"]), events=events, body=body,
        )
        if replayed_text != contract_text:
            raise RuntimeError("FULL_SHORT_CAPTURE_REPLAY_ADAPTER_PROJECTION_DRIFT")
        # The exact business outcome is proved below by feeding every raw
        # capture back through the real adapter, PTR9 guard, Contract Runtime,
        # schema and domain validators in a fresh isolated workflow.  This
        # local check binds the post-adapter bytes to the raw projection.
        if attempt.get("state") == "LOCAL_ATTEMPT_REJECTED":
            business_rejections += 1
        converted_contracts += 1
        replayed_domains += 1
    if len(indexed) != replayed_domains:
        raise RuntimeError("FULL_SHORT_CAPTURE_REPLAY_ORPHAN_CAPTURE")
    return {
        "capture_ledger_anchors_and_adapter_projection_exact": True,
        "replayed_capture_domain_count": replayed_domains,
        "replayed_contract_conversion_count": converted_contracts,
        "replayed_business_rejection_count": business_rejections,
    }


async def _replay_full_workflow_from_captured_bytes(
    *, repo: Path, source_project: Path, project_id: str,
    replay_target: Path, capture_store: ProviderResponseCaptureStoreV1,
    ledger: dict[str, Any], source_call_plan: list[dict[str, Any]],
    expected_final_artifact_sha256: str,
    offline_planning_deepseek_official_fixture: bool = False,
) -> dict[str, Any]:
    replay_execution_id = ledger.get("execution_id")
    if not isinstance(replay_execution_id, str) or not replay_execution_id.strip():
        raise RuntimeError(
            "FULL_SHORT_CAPTURE_REPLAY_EXECUTION_ID_INVALID"
        )
    replay_data = _copy_private_data(
        repo=repo, source_project=source_project, project_id=project_id,
        target=replay_target,
        install_offline_gateway_context_manifest=True,
        private_role_binding_overrides=((
            "planning",
            "0e6a5627-5882-40df-bca5-7d98b97fdd0b",
            "e4b6f0b8-3c5e-412e-8d4e-8453c840a032",
            None,
            None,
        ),) if offline_planning_deepseek_official_fixture else (),
    )
    factory = _CapturedResponseReplayTransportFactory(
        capture_store=capture_store, ledger=ledger,
        source_call_plan=source_call_plan,
    )
    db = Database(replay_data / "app.db")
    registry = _LowestHttpSeamRegistry(
        db, _memory_secrets(replay_data)(),
        http_transport_factory=factory,
        transport_policy=SingleDispatchTransportPolicyV1.phase_b(),
    )
    _db, _project, result = await _await_with_registry_close(
        lambda: run_full_short_workflow_path(
            repo=repo, data_dir=replay_data, project_id=project_id,
            # Provider requests may bind the parent run identity.  A fresh
            # isolated database prevents collision while preserving the exact
            # source request identity required by byte-for-byte replay.
            execution_id=replay_execution_id, registry=registry,
        ),
        registry,
    )
    if result.get("status") != "completed":
        raise RuntimeError(
            "FULL_SHORT_CAPTURE_REPLAY_WORKFLOW_FAILED:"
            + json.dumps({
                "status": result.get("status"),
                "current_stage": result.get("current_stage"),
                "error_present": bool(result.get("error")),
                "error_sha256": _optional_text_sha256(result.get("error")),
                "mock_transport_failure": factory.failure,
                "observed_call_count": len(factory.call_plan),
                "observed_call_tail": factory.call_plan[-5:],
            }, ensure_ascii=True, sort_keys=True)
        )
    if factory.call_plan != source_call_plan:
        raise RuntimeError("FULL_SHORT_CAPTURE_REPLAY_CALL_PLAN_DRIFT")
    replayed_manuscript = (
        replay_data / "projects" / source_project.name
        / "manuscript" / "story.md"
    )
    replayed_artifact_sha256 = _sha256(replayed_manuscript)
    if replayed_artifact_sha256 != expected_final_artifact_sha256:
        raise RuntimeError("FULL_SHORT_CAPTURE_REPLAY_FINAL_ARTIFACT_DRIFT")
    return {
        "all_captured_synthetic_responses_exactly_replayable": True,
        "replay_reentered_real_provider_adapter": True,
        "replay_reentered_ptr9_guard_path": True,
        "replay_reentered_contract_runtime_and_domain_validators": True,
        "replay_call_count": len(factory.call_plan),
        "replay_final_artifact_sha256": replayed_artifact_sha256,
    }


def _canonical_json_bytes_v1(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _exclusive_evidence_write_v1(path: Path, raw: bytes) -> dict[str, str]:
    """Persist one immutable evidence object without replacing prior bytes."""

    if not raw:
        raise RuntimeError("FULL_SHORT_DRY_GATE_EVIDENCE_EMPTY")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        offset = 0
        while offset < len(raw):
            written = os.write(descriptor, raw[offset:])
            if written <= 0:
                raise RuntimeError("FULL_SHORT_DRY_GATE_WRITE_NO_PROGRESS")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return {
        "path": str(path.resolve(strict=True)),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _require_external_evidence_directory_v1(repo: Path, target: Path) -> Path:
    repo = repo.resolve(strict=True)
    target = target.resolve()
    if target == repo or target.is_relative_to(repo):
        raise RuntimeError("FULL_SHORT_DRY_GATE_EVIDENCE_MUST_BE_OUTSIDE_GIT")
    target.mkdir(parents=True, exist_ok=True)
    if any(target.iterdir()):
        raise RuntimeError("FULL_SHORT_DRY_GATE_EVIDENCE_DIRECTORY_NOT_EMPTY")
    return target


def persist_full_short_isolated_dry_run_evidence_v1(
    *, repo: Path, gate_evidence_dir: Path, source_head: str,
    project_id: str, execution_data: Path, project_root: Path,
    run_root: Path, store_root: Path, completion: dict[str, Any],
    terminal: dict[str, Any], workflow_result: dict[str, Any],
    base_runtime_authority: dict[str, Any],
    project_workload: dict[str, Any],
    runtime_authority_sha256: str,
    workload_sha256: str,
    base_story_state_data: dict[str, Any],
    policy: dict[str, Any], public_bindings: dict[str, Any],
    authorization_raw: bytes, replay_proof: dict[str, Any],
) -> dict[str, str]:
    """Export the actual isolated authority chain before temp cleanup.

    The exported files are private external evidence.  Hashes are derived from
    the exact completed control-plane objects and isolated project/database
    bytes; callers cannot supply free-standing receipt hashes.
    """

    target = _require_external_evidence_directory_v1(repo, gate_evidence_dir)
    project_sha256 = hashlib.sha256(project_id.encode("utf-8")).hexdigest()
    if workflow_result.get("status") != "completed":
        raise RuntimeError("FULL_SHORT_DRY_GATE_WORKFLOW_NOT_COMPLETED")
    if (
        completion.get("schema") != "FullShortCompletionReceiptV1"
        or terminal.get("schema") != "ShortCompletionVerificationV1"
        or completion.get("completion_receipt_sha256") is None
        or terminal.get("verification_receipt_sha256") is None
    ):
        raise RuntimeError("FULL_SHORT_DRY_GATE_CONTROL_PLANE_INVALID")

    completion_paths = sorted(store_root.glob("*.completion.json"))
    if len(completion_paths) != 1:
        raise RuntimeError("FULL_SHORT_DRY_GATE_COMPLETION_FILE_AMBIGUOUS")
    completion_raw = completion_paths[0].read_bytes()
    try:
        persisted_completion = json.loads(completion_raw.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise RuntimeError("FULL_SHORT_DRY_GATE_COMPLETION_FILE_INVALID") from exc
    if persisted_completion != completion:
        raise RuntimeError("FULL_SHORT_DRY_GATE_COMPLETION_OBJECT_DRIFT")
    try:
        authorization = validate_full_short_canonical_authorization_v1(
            authorization_raw, policy=policy, public_bindings=public_bindings,
        )
        if (
            authorization.get("policy") != policy
            or authorization.get("public_bindings") != public_bindings
            or policy.get("run_id") != EXECUTION_ID
            or public_bindings.get("run_id") != EXECUTION_ID
        ):
            raise ValueError("dry authorization identity drift")
        durable_store = FullShortDurableExecutionStoreV1(
            repo_root=repo, store_root=store_root,
        )
        permission = FullShortDurableExecutionStoreV1._verify_seal(
            durable_store._read(EXECUTION_ID, "permission"),
            domain="novel-flywheel-full-short-permission-v1",
            field="permission_sha256", reason="PERMISSION_SHA256_MISMATCH",
        )
        approval = FullShortDurableExecutionStoreV1._verify_seal(
            durable_store._read(EXECUTION_ID, "approval"),
            domain="novel-flywheel-full-short-jit-approval-v1",
            field="signed_approval_sha256", reason="APPROVAL_SHA256_MISMATCH",
        )
        nonce = FullShortDurableExecutionStoreV1._verify_seal(
            durable_store._read(EXECUTION_ID, "nonce"),
            domain="novel-flywheel-full-short-nonce-record-v1",
            field="nonce_record_sha256", reason="NONCE_SHA256_MISMATCH",
        )
        ledger = durable_store.load_ledger(EXECUTION_ID)
        capacity_receipts = durable_store.verify_completion_capacity_receipts(
            execution_id=EXECUTION_ID, policy=policy, ledger=ledger,
        )
        durable_store.verify_completion_capture_receipts(
            execution_id=EXECUTION_ID, policy=policy, ledger=ledger,
        )
        rebuilt_completion = build_full_short_completion_receipt_v1(
            execution_id=EXECUTION_ID, policy=policy,
            durable_store=durable_store,
            permission_sha256=permission["permission_sha256"],
            signed_approval_sha256=approval["signed_approval_sha256"],
            nonce_sha256=nonce["nonce_sha256"], ledger=ledger,
            final_bindings=completion["final_bindings"],
            terminal_verification=terminal,
            capacity_admission_receipts=capacity_receipts,
        )
        rebuilt_completion["created_at"] = completion["created_at"]
        rebuilt_completion["completion_receipt_sha256"] = domain_sha256(
            "novel-flywheel-full-short-completion-receipt-v1",
            {
                key: value for key, value in rebuilt_completion.items()
                if key != "completion_receipt_sha256"
            },
        )
        if rebuilt_completion != completion:
            raise ValueError("completion rebuild drift")
        runtime_journal_path = (
            store_root / f"{EXECUTION_ID}.runtime-journal-v1.json"
        )
        runtime_journal = DurableExecutionJournalV1.open(runtime_journal_path)
        if (
            runtime_journal.execution_id != EXECUTION_ID
            or runtime_journal.state is not ExecutionState.COMPLETED
        ):
            raise ValueError("runtime journal is not completed")
    except Exception as exc:
        raise RuntimeError("FULL_SHORT_DRY_GATE_DURABLE_CHAIN_INVALID") from exc

    story_state = StoryStateStore(Database(execution_data / "app.db")).get(
        project_id
    )
    if story_state is None:
        raise RuntimeError("FULL_SHORT_DRY_GATE_STORY_STATE_MISSING")
    story_state_sha256 = canonical_json_sha256(story_state.data)
    final_bindings = completion.get("final_bindings") or {}
    if (
        final_bindings.get("story_state_sha256") != story_state_sha256
        or final_bindings.get("terminal_verification_sha256")
        != terminal["verification_receipt_sha256"]
    ):
        raise RuntimeError("FULL_SHORT_DRY_GATE_AUTHORITY_BINDING_DRIFT")
    story_state_snapshot = {
        "schema": "FullShortStoryStateAuthoritySnapshotV1",
        "version": 1,
        "project_id_sha256": project_sha256,
        "revision": story_state.revision,
        "data": story_state.data,
        "authority_sha256": story_state_sha256,
    }

    manuscript_path = project_root / "manuscript" / "story.md"
    chapter_path = project_root / "chapters" / "chapter-01.md"
    canon_path = project_root / "memory" / "canon.json"
    project_path = project_root / "project.json"
    constraints_path = project_root / "constraints.md"
    quality_checkpoint_path = run_root / "outputs" / "quality-checkpoint.json"
    journal_path = project_mutation_journal_path(project_root, EXECUTION_ID)
    journal_raw = journal_path.read_bytes()
    journal = ProjectMutationJournalV1.model_validate_json(journal_raw)
    if (
        journal.status != "committed"
        or journal.project_id != project_id
        or journal.run_id != EXECUTION_ID
        or journal.story_state is None
        or journal.story_state.target_revision != story_state.revision
        or journal.story_state.state_sha256 != story_state_sha256
        or journal.story_state.data != story_state.data
        or journal.post_commit_gate is None
        or journal.post_commit_gate.status != "passed"
        or not journal.post_commit_gate.receipt_path
        or not journal.post_commit_gate.receipt_sha256
    ):
        raise RuntimeError("FULL_SHORT_DRY_GATE_JOURNAL_AUTHORITY_INVALID")
    ready_path = project_root / journal.post_commit_gate.receipt_path
    source_files = {
        "final_artifact": manuscript_path,
        "chapter": chapter_path,
        "canon": canon_path,
        "ready": ready_path,
        "project_mutation_journal": journal_path,
        "project": project_path,
        "constraints": constraints_path,
        "quality_checkpoint": quality_checkpoint_path,
    }
    source_bytes = {name: path.read_bytes() for name, path in source_files.items()}
    source_hashes = {
        name: hashlib.sha256(raw).hexdigest()
        for name, raw in source_bytes.items()
    }
    try:
        project_document = json.loads(source_bytes["project"].decode("utf-8"))
        quality_checkpoint = json.loads(
            source_bytes["quality_checkpoint"].decode("utf-8")
        )
        manuscript_text = source_bytes["final_artifact"].decode("utf-8")
        manuscript_text = manuscript_text.replace("\r\n", "\n").replace("\r", "\n")
        source_hashes["final_artifact_text"] = hashlib.sha256(
            manuscript_text.encode("utf-8")
        ).hexdigest()
    except (UnicodeError, ValueError, TypeError) as exc:
        raise RuntimeError("FULL_SHORT_DRY_GATE_AUTHORITY_FILE_INVALID") from exc
    narrative_integrity_reference = quality_checkpoint.get(
        "narrative_integrity"
    ) if isinstance(quality_checkpoint, dict) else None
    if (
        not isinstance(narrative_integrity_reference, dict)
        or set(narrative_integrity_reference) != {"path", "sha256"}
        or not isinstance(narrative_integrity_reference.get("path"), str)
        or not narrative_integrity_reference["path"].startswith("outputs/")
    ):
        raise RuntimeError("FULL_SHORT_DRY_GATE_NARRATIVE_INTEGRITY_INVALID")
    narrative_integrity_path = (
        run_root / narrative_integrity_reference["path"]
    ).resolve()
    try:
        narrative_integrity_path.relative_to(run_root.resolve(strict=True))
        narrative_integrity_raw = narrative_integrity_path.read_bytes()
    except (OSError, ValueError):
        raise RuntimeError(
            "FULL_SHORT_DRY_GATE_NARRATIVE_INTEGRITY_INVALID"
        ) from None
    narrative_integrity_sha256 = hashlib.sha256(
        narrative_integrity_raw
    ).hexdigest()
    if (
        not narrative_integrity_raw
        or narrative_integrity_reference.get("sha256")
        != narrative_integrity_sha256
    ):
        raise RuntimeError("FULL_SHORT_DRY_GATE_NARRATIVE_INTEGRITY_INVALID")
    try:
        base_revision = int(base_runtime_authority["story_state_revision"])
        base_authority_sha256 = str(
            base_runtime_authority["story_state_sha256"]
        )
        maintenance_source_state_sha256 = str(
            base_runtime_authority["maintenance_source_state_sha256"]
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("FULL_SHORT_DRY_GATE_BASE_AUTHORITY_INVALID") from exc
    if (
        story_state.revision != base_revision + 1
        or journal.expected_story_state_revision != base_revision
        or journal.story_state is None
        or journal.story_state.expected_revision != base_revision
    ):
        raise RuntimeError("FULL_SHORT_DRY_GATE_BASE_AUTHORITY_DRIFT")
    if canonical_json_sha256(base_story_state_data) != base_authority_sha256:
        raise RuntimeError("FULL_SHORT_DRY_GATE_BASE_AUTHORITY_DRIFT")
    base_story_state_snapshot = {
        "schema": "FullShortBaseStoryStateAuthoritySnapshotV1",
        "version": 1,
        "project_id_sha256": project_sha256,
        "revision": base_revision,
        "data": base_story_state_data,
        "authority_sha256": base_authority_sha256,
    }
    artifact_binding_checks = {
        "completion.manuscript_sha256": (
            final_bindings.get("manuscript_sha256"),
            source_hashes["final_artifact_text"],
        ),
        "completion.chapter_sha256": (
            final_bindings.get("chapter_sha256"), source_hashes["chapter"],
        ),
        "completion.canon_sha256": (
            final_bindings.get("canon_sha256"), source_hashes["canon"],
        ),
        "terminal.final_manuscript_sha256": (
            terminal.get("final_manuscript_sha256"), source_hashes["final_artifact_text"],
        ),
        "journal.ready_receipt_sha256": (
            journal.post_commit_gate.receipt_sha256, source_hashes["ready"],
        ),
        "project.runtime_authority": (
            source_hashes["project"], base_runtime_authority.get("project_json_sha256"),
        ),
        "project.workload": (
            source_hashes["project"], project_workload.get("project_json_sha256"),
        ),
        "constraints.workload": (
            source_hashes["constraints"], project_workload.get("constraints_sha256"),
        ),
        "quality.manuscript_hash": (
            quality_checkpoint.get("manuscript_hash") if isinstance(quality_checkpoint, dict) else None,
            source_hashes["final_artifact_text"],
        ),
        "quality.terminal_reviewed_hash": (
            quality_checkpoint.get("terminal_reviewed_hash") if isinstance(quality_checkpoint, dict) else None,
            source_hashes["final_artifact_text"],
        ),
        "completion.quality_checkpoint_sha256": (
            final_bindings.get("quality_checkpoint_sha256"), source_hashes["quality_checkpoint"],
        ),
        "terminal.final_checkpoint_sha256": (
            (terminal.get("final_checkpoint") or {}).get("checkpoint_sha256"),
            source_hashes["quality_checkpoint"],
        ),
    }
    artifact_binding_drift = {
        key: {"observed_sha256": _domain(observed), "expected_sha256": _domain(expected)}
        for key, (observed, expected) in artifact_binding_checks.items()
        if observed != expected
    }
    if (
        artifact_binding_drift
        or final_bindings.get("manuscript_sha256") != source_hashes["final_artifact_text"]
        or final_bindings.get("chapter_sha256") != source_hashes["chapter"]
        or final_bindings.get("canon_sha256") != source_hashes["canon"]
        or final_bindings.get("terminal_verification_sha256")
        != terminal["verification_receipt_sha256"]
        or terminal.get("final_manuscript_sha256")
        != source_hashes["final_artifact_text"]
        or terminal.get("completion_goal_outcome") != COMPLETION_GOAL
        or journal.post_commit_gate.receipt_sha256 != source_hashes["ready"]
        or source_hashes["project"]
        != base_runtime_authority.get("project_json_sha256")
        or source_hashes["project"]
        != project_workload.get("project_json_sha256")
        or source_hashes["constraints"]
        != project_workload.get("constraints_sha256")
        or _domain(base_runtime_authority) != runtime_authority_sha256
        or _domain(project_workload) != workload_sha256
        or not isinstance(project_document, dict)
        or project_document.get("id") != project_id
        or project_document.get("target_words")
        != project_workload.get("target_words")
        or not isinstance(quality_checkpoint, dict)
        or quality_checkpoint.get("manuscript_hash")
        != source_hashes["final_artifact_text"]
        or quality_checkpoint.get("terminal_reviewed_hash")
        != source_hashes["final_artifact_text"]
        or final_bindings.get("quality_checkpoint_sha256")
        != source_hashes["quality_checkpoint"]
        or (terminal.get("final_checkpoint") or {}).get("checkpoint_sha256")
        != source_hashes["quality_checkpoint"]
    ):
        raise RuntimeError(
            "FULL_SHORT_DRY_GATE_ARTIFACT_BINDING_DRIFT:"
            + json.dumps(artifact_binding_drift, ensure_ascii=True, sort_keys=True)
        )

    references: dict[str, Any] = {
        "completion": _exclusive_evidence_write_v1(
            target / "completion-receipt.json",
            _canonical_json_bytes_v1(completion),
        ),
        "terminal_verification": _exclusive_evidence_write_v1(
            target / "terminal-verification.json",
            _canonical_json_bytes_v1(terminal),
        ),
        "story_state": _exclusive_evidence_write_v1(
            target / "story-state-authority.json",
            _canonical_json_bytes_v1(story_state_snapshot),
        ),
        "base_story_state": _exclusive_evidence_write_v1(
            target / "base-story-state-authority.json",
            _canonical_json_bytes_v1(base_story_state_snapshot),
        ),
        "project": _exclusive_evidence_write_v1(
            target / "project.json", source_bytes["project"],
        ),
        "constraints": _exclusive_evidence_write_v1(
            target / "constraints.md", source_bytes["constraints"],
        ),
        "quality_checkpoint": _exclusive_evidence_write_v1(
            target / "quality-checkpoint.json",
            source_bytes["quality_checkpoint"],
        ),
        "narrative_integrity": _exclusive_evidence_write_v1(
            target / "narrative-integrity.json", narrative_integrity_raw,
        ),
        "canonical_authorization": _exclusive_evidence_write_v1(
            target / "canonical-authorization.json", authorization_raw,
        ),
        "authorization_policy": _exclusive_evidence_write_v1(
            target / "authorization-policy.json",
            _canonical_json_bytes_v1(policy),
        ),
        "authorization_public_bindings": _exclusive_evidence_write_v1(
            target / "authorization-public-bindings.json",
            _canonical_json_bytes_v1(public_bindings),
        ),
        "runtime_journal": _exclusive_evidence_write_v1(
            target / "runtime-journal-v1.json",
            runtime_journal_path.read_bytes(),
        ),
        "replay_proof": _exclusive_evidence_write_v1(
            target / "captured-response-replay-proof.json",
            _canonical_json_bytes_v1(replay_proof),
        ),
    }
    control_store: dict[str, dict[str, str]] = {}
    for kind in ("permission", "approval", "nonce", "ledger", "completion"):
        path = durable_store._path(EXECUTION_ID, kind)
        control_store[kind] = _exclusive_evidence_write_v1(
            target / f"durable-{kind}.json", path.read_bytes(),
        )
    references["control_store"] = control_store
    references["capacity_admission_receipts"] = [
        _exclusive_evidence_write_v1(
            target / f"capacity-admission-{index:03d}.json",
            path.read_bytes(),
        )
        for index, path in enumerate(
            sorted(durable_store.capacity_receipt_root.glob("*.json")), 1,
        )
    ]
    references["capture_anchors"] = [
        _exclusive_evidence_write_v1(
            target / f"capture-anchor-{index:03d}.json", path.read_bytes(),
        )
        for index, path in enumerate(
            sorted(durable_store.capture_anchor_root.glob("*.json")), 1,
        )
    ]
    capture_root = store_root / "provider-response-captures-v1"
    references["provider_response_captures"] = [
        {
            "relative_path": path.relative_to(capture_root).as_posix(),
            "evidence": _exclusive_evidence_write_v1(
                target / f"provider-capture-{index:03d}.bin",
                path.read_bytes(),
            ),
        }
        for index, path in enumerate(
            sorted(item for item in capture_root.rglob("*") if item.is_file()),
            1,
        )
    ]
    output_names = {
        "final_artifact": "final-artifact.md",
        "chapter": "chapter-01.md",
        "canon": "canon.json",
        "ready": "ready-receipt.json",
        "project_mutation_journal": "project-mutation-journal.json",
    }
    for name, output_name in output_names.items():
        references[name] = _exclusive_evidence_write_v1(
            target / output_name, source_bytes[name],
        )

    stage_artifacts: dict[str, dict[str, str]] = {}
    for name in sorted(_FULL_SHORT_REQUIRED_ARTIFACTS):
        path = run_root / "outputs" / name
        if not path.is_file():
            raise RuntimeError("FULL_SHORT_DRY_GATE_REQUIRED_ARTIFACT_MISSING")
        stage_artifacts[name] = _exclusive_evidence_write_v1(
            target / f"stage-{name}", path.read_bytes(),
        )
    references["stage_artifacts"] = stage_artifacts

    maintenance_receipts = []
    maintenance_paths = sorted(
        (run_root / "receipts").glob("maintenance-inventory-*.json")
    ) + sorted((run_root / "receipts").glob("maintenance-reduction-*.json"))
    if not maintenance_paths:
        raise RuntimeError("FULL_SHORT_DRY_GATE_MAINTENANCE_EVIDENCE_MISSING")
    for index, path in enumerate(maintenance_paths, 1):
        raw = path.read_bytes()
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeError, ValueError) as exc:
            raise RuntimeError("FULL_SHORT_DRY_GATE_MAINTENANCE_INVALID") from exc
        try:
            if value.get("schema") == "MaintenanceProposalInventoryV1":
                inventory = MaintenanceProposalInventoryV1.model_validate_json(raw)
                if (
                    inventory.complete is not True
                    or inventory.coverage_gaps
                    or inventory.source_artifact_hash
                    != source_hashes["final_artifact_text"]
                    or inventory.base_authority_revision != base_revision
                    or inventory.base_authority_hash != base_authority_sha256
                ):
                    raise ValueError("maintenance inventory authority drift")
                kind = "MaintenanceProposalInventoryV1"
            elif value.get("version") == "maintenance-reduction-v1":
                validate_maintenance_reduction(
                    value,
                    manuscript=source_bytes["final_artifact"].decode("utf-8"),
                    source_state_sha256=maintenance_source_state_sha256,
                )
                kind = "MaintenanceReductionV1"
            else:
                raise ValueError("unknown maintenance authority artifact")
        except (UnicodeError, TypeError, ValueError) as exc:
            raise RuntimeError("FULL_SHORT_DRY_GATE_MAINTENANCE_INVALID") from exc
        maintenance_receipts.append({
            "kind": kind,
            "evidence": _exclusive_evidence_write_v1(
                target / f"maintenance-authority-{index:02d}.json", raw,
            ),
        })
    maintenance_model_receipt = run_root / "receipts" / "maintenance.json"
    maintenance_output = run_root / "outputs" / "maintenance.md"
    try:
        model_receipt_value = json.loads(
            maintenance_model_receipt.read_text(encoding="utf-8")
        )
        maintenance_output_value = json.loads(
            maintenance_output.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, ValueError) as exc:
        raise RuntimeError("FULL_SHORT_DRY_GATE_MAINTENANCE_INVALID") from exc
    try:
        validate_short_maintenance_business_complete_v2(
            maintenance_output_value,
            expected_manuscript_sha256=source_hashes["final_artifact_text"],
        )
    except (TypeError, ValueError) as exc:
        raise RuntimeError("FULL_SHORT_DRY_GATE_MAINTENANCE_INVALID") from exc
    inventory_modes = {
        json.loads(path.read_text(encoding="utf-8")).get("source_mode")
        for path in maintenance_paths
        if path.name.startswith("maintenance-inventory-")
    }
    reduction_present = any(
        path.name.startswith("maintenance-reduction-")
        for path in maintenance_paths
    )
    normal_lane_exact = bool(
        "normal" in inventory_modes
        and isinstance(model_receipt_value, dict)
        and isinstance(model_receipt_value.get("model"), dict)
        and model_receipt_value["model"].get("role") == "maintenance"
        and isinstance(maintenance_output_value, dict)
    )
    completed_maintenance = [
        item for item in (ledger.get("completed_stage_receipts") or [])
        if item.get("role") == "maintenance"
    ]
    if len(completed_maintenance) != 1:
        raise RuntimeError("FULL_SHORT_DRY_GATE_MAINTENANCE_INVALID")
    completed_maintenance_receipt = completed_maintenance[0]
    accepted_attempt = [
        item for item in (ledger.get("attempts") or [])
        if item.get("physical_attempt_id")
        == completed_maintenance_receipt.get("accepted_physical_attempt_id")
    ]
    model_body = model_receipt_value.get("model") or {}
    if (
        completed_maintenance_receipt.get("output_sha256")
        != hashlib.sha256(maintenance_output.read_bytes()).hexdigest()
        or completed_maintenance_receipt.get("receipt_sha256")
        != hashlib.sha256(maintenance_model_receipt.read_bytes()).hexdigest()
        or len(accepted_attempt) != 1
        or accepted_attempt[0].get("state") != "LOCAL_STAGE_COMPLETE"
        or accepted_attempt[0].get("bound_role") != "maintenance"
        or accepted_attempt[0].get("provider_protocol_capture_receipt_sha256")
        is None
        or model_body.get("role") != "maintenance"
        or hashlib.sha256(
            str(model_body.get("provider_id") or "").encode("utf-8")
        ).hexdigest() != accepted_attempt[0].get("provider_id_sha256")
        or hashlib.sha256(
            str(model_body.get("model_id") or "").encode("utf-8")
        ).hexdigest() != accepted_attempt[0].get("model_id_sha256")
        or model_body.get("route_fingerprint")
        != accepted_attempt[0].get("route_fingerprint")
    ):
        raise RuntimeError("FULL_SHORT_DRY_GATE_MAINTENANCE_INVALID")
    if not any(
        item["kind"] == "MaintenanceProposalInventoryV1"
        for item in maintenance_receipts
    ) or not (normal_lane_exact or reduction_present):
        raise RuntimeError("FULL_SHORT_DRY_GATE_MAINTENANCE_INVALID")
    references["maintenance_model_receipt"] = _exclusive_evidence_write_v1(
        target / "maintenance-model-receipt.json",
        maintenance_model_receipt.read_bytes(),
    )
    references["maintenance_output"] = _exclusive_evidence_write_v1(
        target / "maintenance-output.json", maintenance_output.read_bytes(),
    )
    references["maintenance_receipts"] = maintenance_receipts

    manifest = {
        "schema": "FullShortIsolatedDryRunEvidenceManifestV2",
        "version": 2,
        "source_head": source_head,
        "project_id_sha256": project_sha256,
        "execution_id_sha256": hashlib.sha256(
            EXECUTION_ID.encode("utf-8")
        ).hexdigest(),
        "execution_id": EXECUTION_ID,
        "durable_store": {
            "root": str(store_root.resolve(strict=True)),
            "store_root_sha256": durable_store.store_root_sha256,
        },
        "authority_bindings": {
            "completion_receipt_sha256": completion[
                "completion_receipt_sha256"
            ],
            "terminal_verification_sha256": terminal[
                "verification_receipt_sha256"
            ],
            "final_artifact_sha256": source_hashes["final_artifact"],
            "chapter_sha256": source_hashes["chapter"],
            "story_state_sha256": story_state_sha256,
            "canon_sha256": source_hashes["canon"],
            "ready_receipt_sha256": source_hashes["ready"],
            "project_mutation_journal_sha256": source_hashes[
                "project_mutation_journal"
            ],
            "maintenance_artifact_receipt_sha256": (
                terminal.get("maintenance") or {}
            ).get("artifact_receipt_sha256"),
            "required_stage_artifacts_sha256": _domain([
                {"name": name, "sha256": reference["sha256"]}
                for name, reference in sorted(stage_artifacts.items())
            ]),
            "runtime_authority_sha256": runtime_authority_sha256,
            "workload_sha256": workload_sha256,
            "project_json_sha256": source_hashes["project"],
            "constraints_sha256": source_hashes["constraints"],
            "quality_checkpoint_sha256": source_hashes[
                "quality_checkpoint"
            ],
            "narrative_integrity_sha256": narrative_integrity_sha256,
        },
        "maintenance_authority": {
            "base_story_state_revision": base_revision,
            "base_story_state_sha256": base_authority_sha256,
            "live_story_state_revision": story_state.revision,
            "live_story_state_sha256": story_state_sha256,
            "maintenance_source_state_sha256": (
                maintenance_source_state_sha256
            ),
            "source_modes": sorted(
                mode for mode in inventory_modes if isinstance(mode, str)
            ),
            "normal_lane_exact": normal_lane_exact,
            "reduction_lane_exact": reduction_present,
        },
        "receipts": references,
        "external_actions": {
            "credential_lookup": 0,
            "provider_client_creation": 0,
            "provider_request": 0,
            "http_post": 0,
            "network": 0,
            "model": 0,
            "paid": 0,
        },
        "private_isolated_evidence": True,
    }
    return _exclusive_evidence_write_v1(
        target / "isolated-evidence-manifest.json",
        _canonical_json_bytes_v1(manifest),
    )


async def _run(
    args: argparse.Namespace, *, private_root: Path | None = None,
) -> dict[str, Any]:
    repo = args.repo.resolve(strict=True)
    matches = []
    for candidate in (repo / "data" / "projects").glob("*/project.json"):
        try:
            document = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if str(document.get("id")) == args.project_id:
            matches.append(candidate.parent)
    if len(matches) != 1:
        raise ValueError("project id must resolve to exactly one current project")
    source_project = matches[0].resolve(strict=True)
    project_id = args.project_id
    start_head = _git(repo, "rev-parse", "HEAD")
    if _git(repo, "status", "--porcelain"):
        raise RuntimeError("FULL_SHORT_DRY_RUN_REQUIRES_CLEAN_SOURCE_WORKTREE")

    if private_root is None:
        raise ValueError("private_root is required")
    private_root = private_root.resolve(strict=True)
    stable_gate_root: Path | None = None
    if getattr(args, "gate_evidence_dir", None) is not None:
        stable_gate_root = _require_external_evidence_directory_v1(
            repo, Path(args.gate_evidence_dir),
        )
    with nullcontext(str(private_root)) as temp_name:
        private_root = Path(temp_name)
        discovery_data = _copy_private_data(
            repo=repo, source_project=source_project, project_id=project_id,
            target=private_root / "discovery",
            install_offline_gateway_context_manifest=True,
            private_role_binding_overrides=((
                "planning",
                "0e6a5627-5882-40df-bca5-7d98b97fdd0b",
                "e4b6f0b8-3c5e-412e-8d4e-8453c840a032",
                None,
                None,
            ),) if args.offline_planning_deepseek_official_fixture else (),
        )
        call_plan, logical_stage_plan = await _discover_plan(
            repo=repo, data_dir=discovery_data, project_id=project_id,
        )
        execution_data = _copy_private_data(
            repo=repo, source_project=source_project, project_id=project_id,
            target=private_root / "execution",
            install_offline_gateway_context_manifest=True,
            private_role_binding_overrides=((
                "planning",
                "0e6a5627-5882-40df-bca5-7d98b97fdd0b",
                "e4b6f0b8-3c5e-412e-8d4e-8453c840a032",
                None,
                None,
            ),) if args.offline_planning_deepseek_official_fixture else (),
        )
        store_root = (
            stable_gate_root / "durable-control-store"
            if stable_gate_root is not None
            else private_root / "control-store"
        )
        actual, public = collect_live_bindings(
            repo=repo, data_dir=execution_data, project_id=project_id,
            run_id=EXECUTION_ID, logical_stage_plan=logical_stage_plan,
            store_root=store_root,
        )
        base_story_state = StoryStateStore(Database(execution_data / "app.db")).get(
            project_id
        )
        if base_story_state is None:
            raise RuntimeError("FULL_SHORT_DRY_RUN_BASE_STORY_STATE_MISSING")
        if actual["head"] != start_head:
            raise RuntimeError("FULL_SHORT_DRY_RUN_HEAD_DRIFT")
        expected_calls = len(call_plan)
        discovered_roles = tuple(sorted({
            str(item["role"]) for item in call_plan
        }))
        if not set(FULL_SHORT_REQUIRED_EXECUTION_ROLES).issubset(
            discovered_roles
        ):
            raise RuntimeError("FULL_SHORT_DRY_RUN_PLAN_MISSING_REQUIRED_ROLE")
        per_call_cap = max(
            int(item["requested_output_tokens"]) for item in call_plan
        )
        planning_retry_caps = [
            int(item["requested_output_tokens"])
            for item in call_plan
            if item.get("contract_marker") == "planning_semantic_v2"
        ]
        if not planning_retry_caps:
            raise RuntimeError(
                "FULL_SHORT_DRY_RUN_PLAN_MISSING_PLANNING_REPAIR_BOUNDARY"
            )
        additional_dispatch_hard_cap = sum((
            int(args.inject_planning_business_incomplete_once),
            int(args.inject_planning_reasoning_only_once),
        ))
        if len(planning_retry_caps) < additional_dispatch_hard_cap:
            raise RuntimeError(
                "FULL_SHORT_DRY_RUN_PLAN_MISSING_DISTINCT_RECOVERY_STAGES"
            )
        planning_retry_cap = planning_retry_caps[0]
        planning_recovery_output_token_hard_cap = sum(
            planning_retry_caps[:additional_dispatch_hard_cap]
        )
        discovered_plan_total_cap = sum(
            int(item["requested_output_tokens"]) for item in call_plan
        )
        # Each requested injected recovery owns the second physical slot of a
        # different already-sealed Planning logical stage.  No stage receives
        # a third attempt and no unused global retry topology is authorized.
        hard_max_dispatches = (
            expected_calls + max(1, additional_dispatch_hard_cap)
        )
        total_cap = (
            discovered_plan_total_cap
            + max(
                planning_recovery_output_token_hard_cap,
                int(LOGICAL_STAGE_RECOVERY_POLICY_V1[
                    "recovery_output_tokens"
                ]),
            )
        )
        policy = FullShortExecutionPolicyV1(
            execution_head=actual["head"], branch=actual["branch"],
            run_id=EXECUTION_ID,
            project_id_sha256=actual["project_id_sha256"],
            workload_sha256=actual["workload_sha256"],
            runtime_authority_sha256=actual["runtime_authority_sha256"],
            style_reference_authority_sha256=actual[
                "style_reference_authority_sha256"
            ],
            route_manifest_sha256=actual["route_manifest_sha256"],
            destination_manifest_sha256=actual["destination_manifest_sha256"],
            egress_policy_sha256=actual["egress_policy_sha256"],
            store_root_sha256=actual["store_root_sha256"],
            capture_attestation_public_key=actual[
                "capture_attestation_public_key"
            ],
            capture_attestation_public_key_sha256=actual[
                "capture_attestation_public_key_sha256"
            ],
            required_stage_roles=discovered_roles,
            logical_stage_plan=tuple(logical_stage_plan),
            expected_stage_calls=expected_calls,
            hard_max_provider_requests=hard_max_dispatches,
            hard_max_http_posts=hard_max_dispatches,
            hard_max_network_attempts=hard_max_dispatches,
            per_call_output_token_hard_cap=per_call_cap,
            total_output_token_hard_cap=total_cap,
            maximum_elapsed_seconds=36_000,
            monetary_cost_cap_state="UNKNOWN_NOT_SEALED",
        ).document()
        raw = render_full_short_canonical_authorization_v1(
            policy=policy, public_bindings=public,
        )
        authorization = validate_full_short_canonical_authorization_v1(
            raw, policy=policy, public_bindings=public,
        )
        activated_sha256 = hashlib.sha256(raw).hexdigest()
        control_args = argparse.Namespace(
            repo=repo, data_dir=execution_data, store_root=store_root,
            authorization_raw=raw, activated_sha256=activated_sha256,
        )
        transport = _OfflineHttpTransportFactory(
            inject_planning_business_incomplete_once=(
                args.inject_planning_business_incomplete_once
            ),
            inject_adapter_failure_after_exact_capture_once=(
                args.inject_adapter_failure_after_exact_capture_once
            ),
            inject_planning_reasoning_only_once=(
                args.inject_planning_reasoning_only_once
            ),
        )
        try:
            execution = await _execute_full_short_control_plane_offline(
                control_args, authorization,
                secret_store=_memory_secrets(execution_data)(),
                http_transport_factory=transport,
                required_stage_roles=discovered_roles,
            )
            if transport.registry_close_failure is not None:
                raise transport.registry_close_failure
        except Exception as exc:
            if (
                transport.registry_close_failure is not None
                and exc is not transport.registry_close_failure
            ):
                exc.__cause__ = _secondary_close_cause(
                    exc, transport.registry_close_failure,
                )
            ledger_state: dict[str, Any] | None = None
            ledger_paths = sorted(store_root.glob("*.ledger.json"))
            if len(ledger_paths) == 1:
                ledger = json.loads(ledger_paths[0].read_text(encoding="utf-8"))
                ledger_state = {
                    "state": ledger.get("state"),
                    "attempt_count": len(ledger.get("attempts") or []),
                    "completed_stage_count": len(
                        ledger.get("completed_stage_receipts") or []
                    ),
                    "attempt_state_tail": [
                        {
                            "ordinal": item.get("ordinal"),
                            "state": item.get("state"),
                            "role": item.get("bound_role"),
                            "lane": item.get("bound_lane"),
                            "stage": item.get("stage"),
                            "logical_stage_id": item.get("logical_stage_id"),
                            "logical_stage_ordinal": item.get(
                                "logical_stage_ordinal"
                            ),
                            "local_rejection_failure_kind": item.get(
                                "local_rejection_failure_kind"
                            ),
                        }
                        for item in (ledger.get("attempts") or [])
                    ],
                    "completed_stage_receipts": [
                        {
                            "ordinal": item.get("ordinal"),
                            "logical_stage_id": item.get("logical_stage_id"),
                            "logical_stage_ordinal": item.get(
                                "logical_stage_ordinal"
                            ),
                        }
                        for item in (
                            ledger.get("completed_stage_receipts") or []
                        )
                    ],
                }
            failure_db = Database(execution_data / "app.db")
            run_row = failure_db.get_run(EXECUTION_ID) or {}
            event_tail = [
                {
                    "severity": item.get("severity"),
                    "event_type": item.get("event_type"),
                    "stage": item.get("stage"),
                    "message_present": bool(item.get("message")),
                    "message_sha256": _optional_text_sha256(
                        item.get("message")
                    ),
                    "metadata_keys": sorted(
                        str(key) for key in (item.get("metadata") or {})
                    ),
                    "error_type": (item.get("metadata") or {}).get(
                        "error_type"
                    ),
                    "failure_class": (item.get("metadata") or {}).get(
                        "failure_class"
                    ),
                    "failure_code": (item.get("metadata") or {}).get(
                        "failure_code"
                    ),
                    "failure_family": (item.get("metadata") or {}).get(
                        "failure_family"
                    ),
                    "recovery_action": (item.get("metadata") or {}).get(
                        "recovery_action"
                    ),
                }
                for item in failure_db.list_run_events(EXECUTION_ID)[-15:]
            ]
            raise RuntimeError(
                "FULL_SHORT_DRY_RUN_EXECUTION_FAILED:"
                + json.dumps({
                    **_safe_failure_projection(
                        exc, boundary="full_short_dry_run.execution",
                    ),
                    "mock_transport_failure": transport.failure,
                    "observed_call_count": len(transport.call_plan),
                    "observed_call_tail": transport.call_plan[-5:],
                    "expected_logical_stage_plan_tail": [
                        {
                            "ordinal": item.get("ordinal"),
                            "stage_id": item.get("stage_id"),
                            "role": item.get("role"),
                            "route_lane": item.get("route_lane"),
                        }
                        for item in logical_stage_plan[
                            max(0, len(transport.call_plan) - 2):
                            len(transport.call_plan) + 3
                        ]
                    ],
                    "ledger": ledger_state,
                    "run_state": {
                        "status": run_row.get("status"),
                        "current_stage": run_row.get("current_stage"),
                        "error_present": bool(run_row.get("error")),
                        "error_sha256": _optional_text_sha256(
                            run_row.get("error")
                        ),
                    },
                    "run_event_tail": event_tail,
                    "terminal_failure_projection": {
                        key: value
                        for key, value in (
                            (failure_db.list_run_events(EXECUTION_ID)[-1].get(
                                "metadata"
                            ) or {})
                        ).items()
                        if key in {
                            "error_type", "failure_class", "failure_code",
                            "failure_family", "recovery_action",
                            "failure_contract", "failure_graph",
                            "failure_graph_sha256", "failure_sha256",
                        }
                    } if failure_db.list_run_events(EXECUTION_ID) else None,
                }, ensure_ascii=True, sort_keys=True)
            ) from exc
        observed_plan = execution["call_plan"]
        ledger = execution["ledger"]
        physical_attempt_envelopes = _executed_physical_attempt_envelopes_v1(
            project_root=(
                execution_data / "projects" / source_project.name
            ),
            ledger=ledger,
            observed_plan=observed_plan,
        )
        capture_store = ProviderResponseCaptureStoreV1(
            repo_root=repo,
            store_root=store_root / "provider-response-captures-v1",
        )
        capture_receipts = capture_store.audit_all(
            expected_receipt_sha256s=_capture_receipt_anchors_from_ledger(
                ledger,
            ),
        )
        replay_anchor_proof = _replay_captured_attempts(
            capture_store=capture_store, ledger=ledger,
        )
        source_manuscript = (
            execution_data / "projects" / source_project.name
            / "manuscript" / "story.md"
        )
        expected_final_artifact_sha256 = _sha256(source_manuscript)
        replay_workflow_proof = await _replay_full_workflow_from_captured_bytes(
            repo=repo, source_project=source_project, project_id=project_id,
            # Keep the Windows private-copy path short enough for historical
            # run artifacts whose bounded filenames are already near MAX_PATH.
            replay_target=private_root / "r",
            capture_store=capture_store, ledger=ledger,
            source_call_plan=observed_plan,
            expected_final_artifact_sha256=expected_final_artifact_sha256,
            offline_planning_deepseek_official_fixture=(
                args.offline_planning_deepseek_official_fixture
            ),
        )
        replay_proof = {**replay_anchor_proof, **replay_workflow_proof}
        provider_capture_count = sum(
            item["byte_domain"] == PROVIDER_PROTOCOL_INPUT_BYTES
            for item in capture_receipts
        )
        contract_capture_count = sum(
            item["byte_domain"] == CONTRACT_RUNTIME_INPUT_BYTES
            for item in capture_receipts
        )
        contract_capture_required_count = sum(
            _attempt_requires_contract_runtime_capture_v1(item)
            for item in ledger["attempts"]
        )
        response_capture_receipts_complete = (
            provider_capture_count == len(ledger["attempts"])
            and contract_capture_count == contract_capture_required_count
            and all(
                item.get("provider_protocol_capture_receipt_sha256")
                for item in ledger["attempts"]
            )
            and all(
                not _attempt_requires_contract_runtime_capture_v1(item)
                or item.get("contract_runtime_capture_receipt_sha256")
                for item in ledger["attempts"]
            )
        )
        rejected_ordinals = {
            int(item["ordinal"])
            for item in ledger["attempts"]
            if item.get("state") == "LOCAL_ATTEMPT_REJECTED"
        }
        successful_observed_plan = [
            {**item, "ordinal": index}
            for index, item in enumerate(
                (
                    item for item in observed_plan
                    if int(item["ordinal"]) not in rejected_ordinals
                ),
                1,
            )
        ]
        policy_neutral_keys = (
            "ordinal", "role", "contract_marker",
            "requested_output_tokens", "destination_sha256",
        )
        policy_neutral_observed_plan = [
            {key: item.get(key) for key in policy_neutral_keys}
            for item in successful_observed_plan
        ]
        policy_neutral_discovered_plan = [
            {key: item.get(key) for key in policy_neutral_keys}
            for item in call_plan
        ]
        exact_call_plan_match = successful_observed_plan == call_plan
        isolated_reasoning_recovery_match = (
            args.inject_planning_reasoning_only_once
            and policy_neutral_observed_plan == policy_neutral_discovered_plan
            and sum(
                1 for item in successful_observed_plan
                if item.get("contract_marker") == "planning_semantic_v2"
                and item.get("reasoning_field_present") is True
                and item.get("reasoning_effort") == "none"
            ) == 1
            and all(
                item.get("reasoning_field_present") is False
                for item in call_plan
            )
        )
        # Discovery and execution run under separate durable run identities.
        # Requests whose prompts bind the parent run (for example execution
        # manifest fragments) therefore cannot be byte-identical across those
        # two phases.  Keep the topology exact while reserving full byte
        # equality for captured-response replay below.
        run_bound_execution_plan_match = (
            policy_neutral_observed_plan == policy_neutral_discovered_plan
            and not args.inject_planning_reasoning_only_once
            and all(
                item.get("reasoning_field_present") is False
                for item in call_plan
            )
        )
        if not (
            exact_call_plan_match
            or isolated_reasoning_recovery_match
            or run_bound_execution_plan_match
        ):
            raise RuntimeError("FULL_SHORT_DRY_RUN_CALL_PLAN_DRIFT")
        completion = execution["completion"]
        terminal = execution["terminal"]
        result = execution["workflow_result"]
        summary = {
            "schema": "FirstTrustworthyFullShortPrivateDryRunV2",
            "version": 2,
            "status": "PASS",
            "source_head": start_head,
            "project_id_sha256": hashlib.sha256(project_id.encode()).hexdigest(),
            "workload_sha256": actual["workload_sha256"],
            "runtime_authority_sha256": actual["runtime_authority_sha256"],
            "style_reference_authority_sha256": actual[
                "style_reference_authority_sha256"
            ],
            "route_manifest_sha256": actual["route_manifest_sha256"],
            "destination_manifest_sha256": actual["destination_manifest_sha256"],
            "egress_policy_sha256": actual["egress_policy_sha256"],
            "store_root_sha256": actual["store_root_sha256"],
            "monetary_cost_cap_state": "UNKNOWN_NOT_SEALED",
            "workflow_status": result["status"],
            "completion_goal_outcome": terminal["completion_goal_outcome"],
            "completion_receipt_sha256": completion[
                "completion_receipt_sha256"
            ],
            "discovered_call_plan_sha256": _domain(call_plan),
            "logical_stage_plan_sha256": policy[
                "logical_stage_plan_sha256"
            ],
            "logical_stage_plan": logical_stage_plan,
            "physical_attempt_envelopes": physical_attempt_envelopes,
            "physical_attempt_envelope_count": len(
                physical_attempt_envelopes
            ),
            "physical_attempt_envelopes_complete": (
                len(physical_attempt_envelopes) == len(ledger["attempts"])
                and all(
                    item["total_rendered_input_tokens"] > 0
                    and item["provider_wire_requested_output_cap"] > 0
                    and len(item["input_envelope_sha256"]) == 64
                    for item in physical_attempt_envelopes
                )
            ),
            "transport_recovery_policy_sha256": policy[
                "transport_recovery_policy_sha256"
            ],
            "transport_recovery_policy_identity": policy[
                "transport_recovery_policy_identity"
            ],
            "logical_stage_recovery_policy_sha256": policy[
                "logical_stage_recovery_policy_sha256"
            ],
            "logical_stage_recovery_policy_identity": policy[
                "logical_stage_recovery_policy_identity"
            ],
            "max_physical_attempts_per_logical_stage": 2,
            "executed_call_plan_sha256": _domain(observed_plan),
            "expected_stage_calls": expected_calls,
            "hard_max_provider_requests": hard_max_dispatches,
            "hard_max_http_posts": hard_max_dispatches,
            "hard_max_network_attempts": hard_max_dispatches,
            "per_call_output_token_hard_cap": per_call_cap,
            "total_output_token_hard_cap": total_cap,
            "discovered_plan_output_token_hard_cap": (
                discovered_plan_total_cap
            ),
            "planning_single_repair_output_token_hard_cap": planning_retry_cap,
            "planning_recovery_output_token_hard_cap": (
                planning_recovery_output_token_hard_cap
            ),
            "additional_dispatch_hard_cap": additional_dispatch_hard_cap,
            "maximum_elapsed_seconds": 36_000,
            "provider_request_count": len(ledger["attempts"]),
            "response_capture_policy_sha256": actual[
                "response_capture_policy_sha256"
            ],
            "provider_protocol_capture_count": provider_capture_count,
            "contract_runtime_capture_count": contract_capture_count,
            "contract_runtime_capture_required_count": (
                contract_capture_required_count
            ),
            "response_capture_receipts_created_for_all_synthetic_provider_calls": (
                response_capture_receipts_complete
            ),
            **replay_proof,
            "completed_stage_count": len(
                ledger.get("completed_stage_receipts") or []
            ),
            "local_rejected_attempt_count": len(rejected_ordinals),
            "planning_business_incomplete_injected": (
                transport.oracle.planning_business_incomplete_injected
            ),
            "planning_reasoning_only_injected": (
                transport.planning_reasoning_only_injected
            ),
            "planning_finalization_reasoning_none_request_count": sum(
                1 for item in transport.call_plan
                if item.get("contract_marker") == "planning_semantic_v2"
                and item.get("reasoning_effort") == "none"
            ),
            "offline_planning_deepseek_official_fixture": (
                args.offline_planning_deepseek_official_fixture
            ),
            "adapter_failure_after_exact_capture_injected": (
                transport.adapter_failure_after_exact_capture_injected
            ),
            "adapter_projection_call_count_at_injection": (
                transport.adapter_projection_call_count
            ),
            "adapter_failure_recovered_by_exact_local_replay": (
                transport.adapter_failure_after_exact_capture_injected
                and transport.adapter_projection_call_count == 2
            ),
            "required_stage_roles": list(discovered_roles),
            "completed_stage_roles": sorted(set(execution["observed_roles"])),
            "all_required_stage_roles_completed": set(
                FULL_SHORT_REQUIRED_EXECUTION_ROLES
            ).issubset(execution["observed_roles"]),
            "all_dispatches_locally_closed": all(
                item.get("state") in {
                    "LOCAL_STAGE_COMPLETE", "LOCAL_ATTEMPT_REJECTED",
                }
                for item in ledger["attempts"]
            ),
            "elapsed_seconds_at_completion_recheck": execution[
                "elapsed_seconds_at_completion_recheck"
            ],
            "final_artifact_sha256": expected_final_artifact_sha256,
            "dry_run_namespace": "two_isolated_temporary_copies",
            "dry_run_artifacts_cannot_be_mistaken_for_real_output": True,
            "raw_title_persisted": False, "raw_prompt_persisted": False,
            "raw_story_persisted": False, "raw_reference_persisted": False,
            "real_credential_lookup_count": 0,
            "real_provider_client_creation_count": 0,
            "real_provider_request_attempts": 0,
            "real_http_post_attempts": 0, "real_network_calls": 0,
            "real_model_calls": 0, "paid_calls": 0,
            "pass": (
                result["status"] == "completed"
                and terminal["completion_goal_outcome"] == COMPLETION_GOAL
                and len(ledger.get("completed_stage_receipts") or [])
                == expected_calls
                and len(ledger["attempts"])
                == expected_calls + int(
                    args.inject_planning_business_incomplete_once
                ) + int(args.inject_planning_reasoning_only_once)
                and (
                    exact_call_plan_match
                    or isolated_reasoning_recovery_match
                    or run_bound_execution_plan_match
                )
                and transport.oracle.planning_business_incomplete_injected
                is args.inject_planning_business_incomplete_once
                and transport.planning_reasoning_only_injected
                is args.inject_planning_reasoning_only_once
                and (
                    not args.inject_planning_reasoning_only_once
                    or sum(
                        1 for item in transport.call_plan
                        if item.get("contract_marker")
                        == "planning_semantic_v2"
                        and item.get("reasoning_effort") == "none"
                    ) == 1
                )
                and transport.adapter_failure_after_exact_capture_injected
                is args.inject_adapter_failure_after_exact_capture_once
                and (
                    not args.inject_adapter_failure_after_exact_capture_once
                    or transport.adapter_projection_call_count == 2
                )
                and set(FULL_SHORT_REQUIRED_EXECUTION_ROLES).issubset(
                    execution["observed_roles"]
                )
                and all(
                    item.get("state") in {
                        "LOCAL_STAGE_COMPLETE", "LOCAL_ATTEMPT_REJECTED",
                    }
                    for item in ledger["attempts"]
                )
                and response_capture_receipts_complete
                and replay_proof[
                    "all_captured_synthetic_responses_exactly_replayable"
                ]
            ),
        }
        gate_evidence_dir = getattr(args, "gate_evidence_dir", None)
        if gate_evidence_dir is not None:
            manifest_reference = persist_full_short_isolated_dry_run_evidence_v1(
                repo=repo,
                gate_evidence_dir=stable_gate_root / "evidence",
                source_head=start_head,
                project_id=project_id,
                execution_data=execution_data,
                project_root=execution_data / "projects" / source_project.name,
                run_root=(
                    execution_data / "projects" / source_project.name
                    / "runs" / EXECUTION_ID
                ),
                store_root=store_root,
                completion=completion,
                terminal=terminal,
                workflow_result=result,
                base_runtime_authority=dict(public["runtime_authority"]),
                project_workload=dict(public["project_workload"]),
                runtime_authority_sha256=actual[
                    "runtime_authority_sha256"
                ],
                workload_sha256=actual["workload_sha256"],
                base_story_state_data=dict(base_story_state.data),
                policy=policy, public_bindings=public,
                authorization_raw=raw, replay_proof=replay_proof,
            )
            summary["isolated_evidence_manifest"] = manifest_reference
            summary["isolated_gate_evidence_persisted"] = True
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--gate-evidence-dir",
        type=Path,
        help=(
            "empty directory outside the Git worktree for immutable private "
            "isolated gate evidence"
        ),
    )
    parser.add_argument(
        "--inject-planning-business-incomplete-once",
        action="store_true",
    )
    parser.add_argument(
        "--inject-adapter-failure-after-exact-capture-once",
        action="store_true",
    )
    parser.add_argument(
        "--inject-planning-reasoning-only-once",
        action="store_true",
    )
    parser.add_argument(
        "--offline-planning-deepseek-official-fixture",
        action="store_true",
    )
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("output already exists")
    previous_canonical_flag = os.environ.get("NOVEL_SHORT_CANONICAL_V2")
    os.environ["NOVEL_SHORT_CANONICAL_V2"] = "1"
    try:
        summary = _run_with_private_workspace(args)
    finally:
        if previous_canonical_flag is None:
            os.environ.pop("NOVEL_SHORT_CANONICAL_V2", None)
        else:
            os.environ["NOVEL_SHORT_CANONICAL_V2"] = previous_canonical_flag
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=True, sort_keys=True))
    return 0 if summary["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
