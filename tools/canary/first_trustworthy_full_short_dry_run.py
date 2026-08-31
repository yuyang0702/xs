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
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any, Callable

import httpx

from novel_flywheel.db import Database
from novel_flywheel.failure_boundary import failure_evidence_sha256
from novel_flywheel.full_short_execution import (
    FullShortExecutionPolicyV1,
    render_full_short_canonical_authorization_v1,
    validate_full_short_canonical_authorization_v1,
)
from novel_flywheel.models import ModelResult
from novel_flywheel.provider_response_capture import (
    CONTRACT_RUNTIME_INPUT_BYTES,
    PROVIDER_PROTOCOL_INPUT_BYTES,
    ProviderResponseCaptureStoreV1,
)
from novel_flywheel.projects import ProjectStore
from novel_flywheel.providers.http import SingleDispatchTransportPolicyV1
from novel_flywheel.providers.registry import ProviderRegistry
from novel_flywheel.secrets import MemorySecretStore
from tools.canary.fake_boundary import (
    DeterministicShortBoundary,
    _draft_semantic_receipt,
    _execution_manifest_receipt,
)
from tools.canary.short_completion import COMPLETION_GOAL
from tools.canary.first_trustworthy_full_short_runner import (
    FULL_SHORT_REQUIRED_EXECUTION_ROLES,
    collect_live_bindings,
    execute_full_short_control_plane,
    run_full_short_workflow_path,
)


EXECUTION_ID = "private-current-project-dry-run"
DISCOVERY_ID = "private-current-project-call-plan"


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
        segment_match = re.search(
            r"segment-(\d+)", str(contract.get("task_id") or ""), re.IGNORECASE,
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
            actor = actors[(segment + turn) % len(actors)]
            partner = actors[(segment + turn + 2) % len(actors)]
            place = places[(segment * 3 + turn) % len(places)]
            action = actions[(segment + turn * 2) % len(actions)]
            paragraphs.append(
                themes[(segment - 1) % len(themes)]
                + f"第{segment}段第{turn + 1}次核查发生在{place}。"
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
    ) -> None:
        self.oracle = _PrivateDryRunOracle(
            inject_planning_business_incomplete_once=(
                inject_planning_business_incomplete_once
            ),
        )
        self.call_plan: list[dict[str, Any]] = []
        self.failure: dict[str, Any] | None = None

    def build(
        self, *, protocol: str, destination: str, bound_role: str | None = None,
    ) -> httpx.MockTransport:
        async def respond(request: httpx.Request) -> httpx.Response:
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
            self.call_plan.append({
                "ordinal": len(self.call_plan) + 1,
                "role": role,
                "contract_marker": contract_marker,
                "requested_output_tokens": maximum,
                "destination_sha256": hashlib.sha256(
                    destination.encode("utf-8"),
                ).hexdigest(),
                "request_shape_sha256": _domain({
                    "protocol": protocol,
                    "payload_keys": sorted(str(key) for key in payload),
                    "role": role,
                    "requested_output_tokens": maximum,
                }),
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
            return httpx.Response(200, json=body, request=request)

        return httpx.MockTransport(respond)


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
                self._factory.failure = {
                    "boundary": f"attempt_observer.{name}",
                    **_safe_failure_projection(
                        exc, boundary=f"attempt_observer.{name}",
                    ),
                    "reason_code": getattr(exc, "reason_code", None),
                }
                raise

        return call


class _LowestHttpSeamRegistry(ProviderRegistry):
    """Real resolver/adapters with only their HTTP client transport replaced."""

    def __init__(
        self, *args: Any,
        http_transport_factory: _OfflineHttpTransportFactory | None = None,
        **kwargs: Any,
    ) -> None:
        if http_transport_factory is None:
            raise ValueError("offline HTTP transport factory is required")
        self.transport_factory = http_transport_factory
        observer = kwargs.get("attempt_observer")
        if observer is not None:
            kwargs["attempt_observer"] = _DiagnosticObserverProxy(
                observer, http_transport_factory,
            )
        super().__init__(*args, **kwargs)
        self.open_clients: list[httpx.AsyncClient] = []

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
        provider = self.db.get_provider(provider_id) or {}
        protocol = str(provider.get("protocol") or "")
        destination = str(provider.get("base_url") or "").rstrip("/")
        try:
            resolved = super().resolve(
                provider_id, model_id, role=role, lane=lane,
            )
        except Exception as exc:
            self.transport_factory.failure = {
                "boundary": "provider_registry.resolve",
                **_safe_failure_projection(
                    exc, boundary="provider_registry.resolve",
                ),
                "reason_code": getattr(exc, "reason_code", None),
            }
            raise
        previous = resolved.adapter.client
        resolved.adapter.client = httpx.AsyncClient(
            transport=self.transport_factory.build(
                protocol=protocol, destination=destination, bound_role=role,
            ), timeout=30,
        )
        self.open_clients.extend([previous, resolved.adapter.client])
        return resolved

    async def close(self) -> None:
        for client in self.open_clients:
            await client.aclose()
        self.open_clients.clear()


def _registry_factory(*args: Any, **kwargs: Any) -> _LowestHttpSeamRegistry:
    return _LowestHttpSeamRegistry(*args, **kwargs)


def _copy_private_data(
    *, repo: Path, source_project: Path, project_id: str, target: Path,
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
) -> list[dict[str, Any]]:
    factory = _OfflineHttpTransportFactory()
    db = Database(data_dir / "app.db")
    registry = _LowestHttpSeamRegistry(
        db, _memory_secrets(data_dir)(),
        http_transport_factory=factory,
        transport_policy=SingleDispatchTransportPolicyV1.phase_b(),
    )
    try:
        _db, _project, result = await run_full_short_workflow_path(
            repo=repo, data_dir=data_dir, project_id=project_id,
            execution_id=DISCOVERY_ID, registry=registry,
        )
    finally:
        await registry.close()
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
    return registry.call_plan


async def _run(args: argparse.Namespace) -> dict[str, Any]:
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

    with tempfile.TemporaryDirectory(prefix="full-short-private-") as temp_name:
        private_root = Path(temp_name)
        discovery_data = _copy_private_data(
            repo=repo, source_project=source_project, project_id=project_id,
            target=private_root / "discovery",
        )
        call_plan = await _discover_plan(
            repo=repo, data_dir=discovery_data, project_id=project_id,
        )
        execution_data = _copy_private_data(
            repo=repo, source_project=source_project, project_id=project_id,
            target=private_root / "execution",
        )
        store_root = private_root / "control-store"
        actual, public = collect_live_bindings(
            repo=repo, data_dir=execution_data, project_id=project_id,
            run_id=EXECUTION_ID, store_root=store_root,
        )
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
        planning_retry_cap = planning_retry_caps[0]
        discovered_plan_total_cap = sum(
            int(item["requested_output_tokens"]) for item in call_plan
        )
        # This incident authorizes/proves at most one already-existing typed
        # Planning regeneration, not the entire four-attempt topology at every
        # model stage. The normal run therefore leaves one narrow unused slot;
        # the injected run consumes exactly that one slot.
        hard_max_dispatches = expected_calls + 1
        total_cap = discovered_plan_total_cap + planning_retry_cap
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
            required_stage_roles=discovered_roles,
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
        )
        try:
            execution = await execute_full_short_control_plane(
                control_args, authorization,
                external_actions_enabled=False,
                secret_store_factory=_memory_secrets(execution_data),
                registry_factory=_registry_factory,
                http_transport_factory=transport,
                required_stage_roles=discovered_roles,
            )
        except Exception as exc:
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
                            "local_rejection_failure_kind": item.get(
                                "local_rejection_failure_kind"
                            ),
                        }
                        for item in (ledger.get("attempts") or [])[-5:]
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
                }, ensure_ascii=True, sort_keys=True)
            ) from exc
        observed_plan = execution["call_plan"]
        ledger = execution["ledger"]
        capture_store = ProviderResponseCaptureStoreV1(
            repo_root=repo,
            store_root=store_root / "provider-response-captures-v1",
        )
        capture_receipts = capture_store.audit_all()
        provider_capture_count = sum(
            item["byte_domain"] == PROVIDER_PROTOCOL_INPUT_BYTES
            for item in capture_receipts
        )
        contract_capture_count = sum(
            item["byte_domain"] == CONTRACT_RUNTIME_INPUT_BYTES
            for item in capture_receipts
        )
        contract_capture_required_count = sum(
            item.get("contract_runtime_input_required") is True
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
                not item.get("contract_runtime_input_required")
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
        if successful_observed_plan != call_plan:
            raise RuntimeError("FULL_SHORT_DRY_RUN_CALL_PLAN_DRIFT")
        completion = execution["completion"]
        terminal = execution["terminal"]
        result = execution["workflow_result"]
        manuscript = (
            execution_data / "projects" / source_project.name
            / "manuscript" / "story.md"
        )
        summary = {
            "schema": "FirstTrustworthyFullShortPrivateDryRunV2",
            "version": 2,
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
            "additional_dispatch_hard_cap": 1,
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
            "all_captured_synthetic_responses_exactly_replayable": True,
            "completed_stage_count": len(
                ledger.get("completed_stage_receipts") or []
            ),
            "local_rejected_attempt_count": len(rejected_ordinals),
            "planning_business_incomplete_injected": (
                transport.oracle.planning_business_incomplete_injected
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
            "final_artifact_sha256": _sha256(manuscript),
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
                )
                and successful_observed_plan == call_plan
                and transport.oracle.planning_business_incomplete_injected
                is args.inject_planning_business_incomplete_once
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
            ),
        }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--inject-planning-business-incomplete-once",
        action="store_true",
    )
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("output already exists")
    previous_canonical_flag = os.environ.get("NOVEL_SHORT_CANONICAL_V2")
    os.environ["NOVEL_SHORT_CANONICAL_V2"] = "1"
    try:
        summary = asyncio.run(_run(args))
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
