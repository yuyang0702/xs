from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from novel_flywheel.contract_runtime import (
    ContractOutputLimitExhaustedError,
    ExecutableContractSpec,
    execute_contract_runtime,
)
from novel_flywheel.db import Database
from novel_flywheel.generated_artifacts import registered_business_wire_schema
from novel_flywheel.model_diagnostics import ModelDiagnosticContextV1
from novel_flywheel.models import ModelGateway
from novel_flywheel.planning_adaptation import (
    normalize_planning_repair_patch,
    planning_repair_patch_diagnostic_findings,
    planning_repair_patch_diagnostic_policy_sha256,
)
from novel_flywheel.planning_repair_diagnostics import (
    PLANNING_REPAIR_EVIDENCE_FLAG,
    DiagnosticDomainFindingV1,
    build_domain_validation_snapshot,
    build_finding_propagation_snapshot,
    build_output_limit_observation,
    capture_provider_content_block_snapshot,
    finalize_provider_content_block_snapshot,
    planning_repair_diagnostic_metrics_snapshot,
)
from novel_flywheel.providers.openai_chat import OpenAIChatAdapter
from novel_flywheel.providers.registry import ResolvedModel
from novel_flywheel.reliability_trace import read_trace, trace_file_for_project
from novel_flywheel.structured_artifacts import StructuredArtifactContract


SHA = "a" * 64


def context(tmp_path: Path, *, attempt: int = 1, route: str = "primary"):
    project_root = tmp_path / "data" / "projects" / "controlled"
    project_root.mkdir(parents=True, exist_ok=True)
    return ModelDiagnosticContextV1(
        project_root=project_root,
        run_id="controlled-r1-ptr1",
        stage="planning",
        boundary="planning_repair_patch",
        role="planning",
        route_kind=route,
        contract_id="planning_repair_patch",
        contract_version=1,
        outer_retry_ordinal=1,
        inner_attempt_ordinal=attempt,
        parent_attempt_ordinal=attempt - 1 if attempt > 1 else None,
        model_binding_sha256="b" * 64,
        provider_binding_sha256="c" * 64,
        request_parameter_name="max_tokens",
    )


def metadata() -> dict:
    return {
        "repair_target_identity_sha256": "d" * 64,
        "repair_target_sha256": "e" * 64,
        "canonical_repair_target_paths": ["$.replacements[*].replacement"],
        "domain_validator_id": "planning_repair_patch.normalize.v1",
        "domain_validator_policy_sha256": "f" * 64,
    }


def valid_patch() -> dict:
    return {
        "authority_sha256": SHA,
        "segment": 1,
        "replacements": [{
            "evidence_id": "anchor-1",
            "source_sha256": hashlib.sha256("old".encode()).hexdigest(),
            "replacement": "new",
        }],
        "summary": "bounded",
    }


def diagnostic_kwargs() -> dict:
    return {
        "authority_sha256": SHA,
        "segment": 1,
        "evidence_candidates": {"anchor-1": "old"},
        "allowed_anchor_ids": ["anchor-1"],
        "current_segment": "before old after",
    }


def test_domain_valid_snapshot_is_hash_only_and_passed(tmp_path: Path) -> None:
    payload = valid_patch()
    snapshot = build_domain_validation_snapshot(
        context(tmp_path), payload=payload, domain_result="passed",
        findings=[], metadata=metadata(),
    )

    assert snapshot.domain_result == "passed"
    assert snapshot.failure_count == 0
    assert snapshot.normalized_payload_sha256
    assert snapshot.normalized_payload_shape_sha256
    assert snapshot.raw_value_omitted is True
    assert snapshot.raw_story_text_omitted is True
    serialized = json.dumps(snapshot.model_dump(mode="json"), ensure_ascii=False)
    assert "before old after" not in serialized
    assert '"replacement": "new"' not in serialized


def test_schema_valid_domain_invalid_has_exact_rule_and_path(tmp_path: Path) -> None:
    payload = {**valid_patch(), "authority_sha256": "0" * 64}
    findings = planning_repair_patch_diagnostic_findings(
        payload, **diagnostic_kwargs(),
    )
    snapshot = build_domain_validation_snapshot(
        context(tmp_path), payload=payload, domain_result="failed",
        findings=findings, metadata=metadata(),
    )

    assert snapshot.domain_rule_codes == (
        "planning_repair_patch.authority_mismatch",
    )
    assert snapshot.exact_field_paths == ("$.authority_sha256",)
    assert snapshot.invariant_ids == ("repair_authority_fresh",)
    assert snapshot.findings[0].value_type == "string"


def test_multiple_findings_are_deterministically_sorted(tmp_path: Path) -> None:
    findings = [
        DiagnosticDomainFindingV1(
            rule_code="z.rule", field_path="$.z", invariant_id="z",
            value_type="string", structural_shape="scalar",
        ),
        DiagnosticDomainFindingV1(
            rule_code="a.rule", field_path="$.a", invariant_id="a",
            value_type="integer", structural_shape="scalar",
        ),
    ]
    left = build_domain_validation_snapshot(
        context(tmp_path), payload=valid_patch(), domain_result="failed",
        findings=findings, metadata=metadata(),
    )
    right = build_domain_validation_snapshot(
        context(tmp_path), payload=valid_patch(), domain_result="failed",
        findings=list(reversed(findings)), metadata=metadata(),
    )

    assert left.receipt_sha256 == right.receipt_sha256
    assert left.domain_rule_codes == ("a.rule", "z.rule")


def test_current_blind_retry_is_recorded_absent_not_injected(tmp_path: Path) -> None:
    source = build_domain_validation_snapshot(
        context(tmp_path), payload=valid_patch(), domain_result="failed",
        findings=[DiagnosticDomainFindingV1(
            rule_code="a.rule", field_path="$.a", invariant_id="a",
            value_type="string", structural_shape="scalar",
        )], metadata=metadata(),
    )
    propagation = build_finding_propagation_snapshot(
        source=source, target_context=context(tmp_path, attempt=2),
        system="same-system", user="same-user",
        propagated_findings=(), propagated_finding_receipt_sha256=None,
    )

    assert propagation.finding_propagation_status == "absent"
    assert propagation.finding_count == 1
    assert propagation.exact_rule_codes == ("a.rule",)
    assert propagation.raw_prompt_omitted is True


def test_exact_synthetic_propagation_is_identified(tmp_path: Path) -> None:
    finding = DiagnosticDomainFindingV1(
        rule_code="a.rule", field_path="$.a", invariant_id="a",
        value_type="string", structural_shape="scalar",
    )
    source = build_domain_validation_snapshot(
        context(tmp_path), payload=valid_patch(), domain_result="failed",
        findings=[finding], metadata=metadata(),
    )
    propagation = build_finding_propagation_snapshot(
        source=source, target_context=context(tmp_path, attempt=2),
        system="same-system", user="same-user",
        propagated_findings=[finding],
        propagated_finding_receipt_sha256=source.receipt_sha256,
    )

    assert propagation.finding_propagation_status == "exact"


@pytest.mark.parametrize(
    ("case_id", "block_types", "texts", "arguments", "reasoning", "expected"),
    [
        ("empty", [], [], [], 0, (True, 0, 0, 0)),
        ("tool-only", ["tool_call"], [], ["{}"], 0, (False, 1, 0, 0)),
        ("partial-tool", ["tool_call"], [], ["{\"x\":"], 0, (False, 1, 1, 0)),
        ("reasoning-only", ["reasoning"], [], [], 1, (False, 0, 0, 1)),
    ],
)
def test_provider_content_shapes_distinguish_output_limit_topologies(
    case_id, block_types, texts, arguments, reasoning, expected,
    tmp_path: Path,
) -> None:
    snapshot = capture_provider_content_block_snapshot(
        context(tmp_path, attempt=3, route="configured_fallback"),
        adapter_id="openai_chat", adapter_version=1,
        protocol="openai-chat", provider_response={"case": case_id},
        request_max_output_tokens=1977, finish_reason="max_tokens",
        output_tokens=1977, block_types=block_types, text_values=texts,
        tool_arguments=arguments, reasoning_block_count=reasoning,
    )
    assert snapshot is not None
    assert (
        snapshot.empty_content,
        snapshot.tool_call_block_count,
        snapshot.partial_tool_argument_count,
        snapshot.reasoning_block_count,
    ) == expected
    assert snapshot.zero_visible is True
    assert snapshot.max_tokens is True


def test_adapter_pre_and_post_projection_difference_is_visible(tmp_path: Path) -> None:
    before = capture_provider_content_block_snapshot(
        context(tmp_path), adapter_id="openai_chat", adapter_version=1,
        protocol="openai-chat", provider_response={"shape": "tool"},
        request_max_output_tokens=1977, finish_reason="tool_calls",
        output_tokens=20, block_types=["tool_call"], text_values=[],
        tool_arguments=["{\"ok\":true}"], reasoning_block_count=0,
    )
    assert before is not None
    after = finalize_provider_content_block_snapshot(
        before, normalized_text=json.dumps({"ok": True}),
        normalized_tool_call_count=1,
    )
    assert before.normalized_visible_text_chars is None
    assert after.normalized_visible_text_chars > 0
    assert after.adapter_projection_status == "changed"


def test_output_limit_observation_binds_provider_snapshot(tmp_path: Path) -> None:
    provider = capture_provider_content_block_snapshot(
        context(tmp_path, attempt=4, route="configured_fallback"),
        adapter_id="openai_chat", adapter_version=1,
        protocol="openai-chat", provider_response={},
        request_max_output_tokens=3954, finish_reason="max_tokens",
        output_tokens=3954, block_types=[], text_values=[],
        tool_arguments=[], reasoning_block_count=0,
    )
    assert provider is not None
    observation = build_output_limit_observation(
        context(tmp_path, attempt=4, route="configured_fallback"),
        provider_snapshot=provider, requested_budget=3954,
        effective_budget=3954, output_tokens=3954,
        stop_reason="max_tokens", zero_visible=True,
        parser_reached=True, strict_tool_reached=False,
        domain_validator_reached=False,
        truncation_classifier_reason="empty_output",
        contract_output_limit_action="terminal_exhausted",
        expansion_before=3954, expansion_after=7908,
        next_route_action="terminal",
    )
    assert observation.provider_content_block_snapshot_sha256 == (
        provider.snapshot_sha256
    )
    assert observation.expansion_before == 3954
    assert observation.expansion_after == 7908


def test_new_trace_flag_name_is_stable_and_default_off(monkeypatch) -> None:
    monkeypatch.delenv(PLANNING_REPAIR_EVIDENCE_FLAG, raising=False)
    assert PLANNING_REPAIR_EVIDENCE_FLAG == (
        "NOVEL_PLANNING_REPAIR_EVIDENCE_TRACE_V1"
    )
    from tools.canary.approval_profiles import (
        C0B_PROFILE_ID,
        PA_PROFILE_ID,
        SHORT_COMPLETION_PROFILE_ID,
        approval_profile,
    )
    for profile_id in (
        C0B_PROFILE_ID, PA_PROFILE_ID, SHORT_COMPLETION_PROFILE_ID,
    ):
        profile = approval_profile(profile_id)
        assert profile.required_flags()[PLANNING_REPAIR_EVIDENCE_FLAG] is False
        assert PLANNING_REPAIR_EVIDENCE_FLAG in profile.forbidden_feature_flags


class _RouteRegistry:
    def __init__(self, primary, fallback) -> None:
        self.primary = primary
        self.fallback = fallback

    def resolve(self, provider_id, model_id):
        if provider_id == "primary-provider":
            return ResolvedModel(
                provider_id, model_id, "primary-model", self.primary,
                {"structured_output": "strict_tool"},
            )
        return ResolvedModel(
            provider_id, model_id, "fallback-model", self.fallback,
            {"structured_output": "plain_text"},
        )


def _runtime_gateway(tmp_path: Path):
    db = Database(tmp_path / "app.db")
    db.migrate()
    for provider_id in ("primary-provider", "fallback-provider"):
        db.save_provider(
            provider_id=provider_id, name=provider_id,
            protocol="openai-chat", base_url="https://offline.invalid/v1",
            auth_type="bearer", timeout_seconds=30, extra_headers={},
        )
    db.save_model(
        model_id="primary-model", provider_id="primary-provider",
        display_name="primary", model_name="primary-model",
        context_window=100_000, max_output_tokens=None,
        capabilities={"structured_output": "strict_tool"},
    )
    db.save_model(
        model_id="fallback-model", provider_id="fallback-provider",
        display_name="fallback", model_name="fallback-model",
        context_window=100_000, max_output_tokens=None,
        capabilities={"structured_output": "plain_text"},
    )
    db.save_role_binding(
        "planning", "primary-provider", "primary-model",
        "fallback-provider", "fallback-model",
    )
    primary = OpenAIChatAdapter("https://offline.invalid/v1", "not-used")
    fallback = OpenAIChatAdapter("https://offline.invalid/v1", "not-used")
    gateway = ModelGateway(db, _RouteRegistry(primary, fallback))
    gateway.record_structured_contract_outcome = lambda *_args, **_kwargs: None
    return db, primary, fallback, gateway


def _runtime_spec() -> ExecutableContractSpec:
    authority = SHA
    evidence = {"anchor-1": "old"}
    allowed = ["anchor-1"]
    current = "before old after"
    contract = StructuredArtifactContract(
        name="planning_repair_patch",
        version=1,
        schema=registered_business_wire_schema(
            "planning_repair_patch",
            {
                "patch_authority_sha256": authority,
                "segment": 1,
            },
        ),
        runtime_authority={
            "patch_authority_sha256": authority,
            "segment": 1,
        },
    )

    def validate(payload):
        return normalize_planning_repair_patch(
            payload, authority_sha256=authority, segment=1,
            evidence_candidates=evidence, allowed_anchor_ids=allowed,
            current_segment=current,
        )

    def diagnose(payload):
        return planning_repair_patch_diagnostic_findings(
            payload, authority_sha256=authority, segment=1,
            evidence_candidates=evidence, allowed_anchor_ids=allowed,
            current_segment=current,
        )

    return ExecutableContractSpec(
        contract_name="planning_repair_patch",
        structured_contract=contract,
        semantic_normalizer=lambda value: value if isinstance(value, dict) else None,
        domain_validator=validate,
        domain_diagnostic_extractor=diagnose,
        domain_diagnostic_metadata={
            "repair_target_identity_sha256": "d" * 64,
            "repair_target_sha256": authority,
            "canonical_repair_target_paths": [
                "$.replacements[anchor_sha256].replacement",
            ],
            "domain_validator_id": "planning_repair_patch.normalize.v1",
            "domain_validator_policy_sha256": (
                planning_repair_patch_diagnostic_policy_sha256()
            ),
        },
        retry_domain_failures=True,
    )


async def _run_production_shaped_terminal(
    tmp_path: Path, monkeypatch, *, enabled: bool,
):
    monkeypatch.setenv("NOVEL_RELIABILITY_TRACE", "1")
    monkeypatch.setenv(
        PLANNING_REPAIR_EVIDENCE_FLAG, "1" if enabled else "0",
    )
    db, primary, fallback, gateway = _runtime_gateway(tmp_path / "db")
    requests: list[dict] = []
    invalid = {**valid_patch(), "authority_sha256": "0" * 64}

    async def primary_post(_path, *, payload, headers):
        requests.append({
            "route": "primary", "messages": payload["messages"],
            "max_tokens": payload.get("max_tokens"),
            "tool_choice": payload.get("tool_choice"),
        })
        return [], {
            "id": "private-primary-request", "usage": {
                "prompt_tokens": 100, "completion_tokens": 30,
            },
            "choices": [{
                "finish_reason": "tool_calls",
                "message": {"content": None, "tool_calls": [{
                    "id": "private-tool-call",
                    "function": {
                        "name": "planning_repair_patch",
                        "arguments": json.dumps(invalid),
                    },
                }]},
            }],
        }

    async def fallback_post(_path, *, payload, headers):
        budget = int(payload.get("max_tokens") or 0)
        requests.append({
            "route": "configured_fallback",
            "messages": payload["messages"],
            "max_tokens": budget,
            "tool_choice": payload.get("tool_choice"),
        })
        return [], {
            "id": "private-fallback-request", "usage": {
                "prompt_tokens": 100, "completion_tokens": budget,
            },
            "choices": [{
                "finish_reason": "length",
                "message": {"content": "", "tool_calls": []},
            }],
        }

    monkeypatch.setattr(primary, "post_stream", primary_post)
    monkeypatch.setattr(fallback, "post_stream", fallback_post)
    diagnostic_context = context(
        tmp_path / "data", attempt=1, route="primary",
    )
    caught = None
    try:
        await execute_contract_runtime(
            gateway,
            role="planning", system="immutable-system", user="immutable-user",
            execution_spec=_runtime_spec(), max_output_tokens=1977,
            same_route_attempts=2, fallback_attempts=2,
            diagnostic_context=diagnostic_context,
        )
    except ContractOutputLimitExhaustedError as exc:
        caught = exc
    finally:
        await primary.client.aclose()
        await fallback.client.aclose()
    assert caught is not None
    report = read_trace(trace_file_for_project(diagnostic_context.project_root))
    return caught, requests, report, db


@pytest.mark.asyncio
async def test_production_shaped_runtime_captures_domain_blind_retry_and_output_limit(
    tmp_path, monkeypatch,
) -> None:
    _caught, requests, report, _db = await _run_production_shaped_terminal(
        tmp_path, monkeypatch, enabled=True,
    )
    by_type: dict[str, list] = {}
    for event in report.events:
        by_type.setdefault(event.event_type, []).append(event)

    domains = by_type["diagnostic_planning_repair_domain"]
    propagations = by_type[
        "diagnostic_planning_repair_finding_propagation"
    ]
    assert "diagnostic_provider_content_block_shape" in by_type, (
        sorted(by_type), planning_repair_diagnostic_metrics_snapshot(),
    )
    provider_shapes = by_type["diagnostic_provider_content_block_shape"]
    output_limits = by_type["diagnostic_planning_repair_output_limit"]

    assert len(domains) == 2
    assert all(
        item.payload["domain_rule_codes"] == [
            "planning_repair_patch.authority_mismatch",
        ]
        for item in domains
    )
    assert all(
        item.payload["exact_field_paths"] == ["$.authority_sha256"]
        for item in domains
    )
    assert len(propagations) == 3
    assert all(
        item.payload["finding_propagation_status"] == "absent"
        for item in propagations
    )
    assert len(provider_shapes) == 4
    assert [item.payload["route_kind"] for item in provider_shapes] == [
        "primary", "primary", "configured_fallback", "configured_fallback",
    ]
    assert len(output_limits) == 2
    assert output_limits[-1].payload["contract_output_limit_action"] == (
        "terminal_exhausted"
    )
    assert output_limits[-1].payload[
        "provider_content_block_snapshot_sha256"
    ] == provider_shapes[-1].payload["snapshot_sha256"]
    assert [item["max_tokens"] for item in requests] == [
        1977, 1977, 1977, 3954,
    ]
    assert requests[0]["messages"] == requests[1]["messages"]
    assert requests[1]["messages"] == requests[2]["messages"]
    assert requests[2]["messages"] != requests[3]["messages"]
    serialized = json.dumps(
        [item.payload for item in report.events], ensure_ascii=False,
    )
    assert "immutable-system" not in serialized
    assert "immutable-user" not in serialized
    assert "before old after" not in serialized
    assert "private-" not in serialized


@pytest.mark.asyncio
async def test_flag_on_off_preserves_prompt_route_retry_fallback_budget_and_failure(
    tmp_path, monkeypatch,
) -> None:
    disabled, before_requests, before_report, _ = (
        await _run_production_shaped_terminal(
            tmp_path / "off", monkeypatch, enabled=False,
        )
    )
    enabled, after_requests, after_report, _ = (
        await _run_production_shaped_terminal(
            tmp_path / "on", monkeypatch, enabled=True,
        )
    )

    assert type(disabled) is type(enabled)
    assert str(disabled) == str(enabled)
    assert before_requests == after_requests
    assert len(before_requests) == len(after_requests) == 4
    assert before_report.events == []
    assert len(after_report.events) > 0


@pytest.mark.asyncio
async def test_observer_sink_failure_is_fail_open_and_does_not_add_dispatch(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(
        "novel_flywheel.reliability_trace.BestEffortTraceSink.emit",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("sink failed")),
    )
    caught, requests, _report, _db = await _run_production_shaped_terminal(
        tmp_path, monkeypatch, enabled=True,
    )

    assert isinstance(caught, ContractOutputLimitExhaustedError)
    assert [item["max_tokens"] for item in requests] == [
        1977, 1977, 1977, 3954,
    ]


def test_parent_live_parity_and_external_action_baseline_remain_exact() -> None:
    receipt = json.loads((
        Path(__file__).resolve().parents[1]
        / "docs/superpowers/reports/r1-ptr0/r1-ptr0-validation-receipt-v1.json"
    ).read_text(encoding="utf-8"))
    assert receipt["live_parity"]["status"] == "exact"
    assert receipt["live_parity"]["before_sha256"] == (
        receipt["live_parity"]["after_sha256"]
    )
    assert all(value == 0 for value in receipt["external_actions"].values())
