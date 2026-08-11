import json
from pathlib import Path

import pytest

from novel_flywheel.db import Database
from novel_flywheel.production_incidents import (
    classify_production_failure,
    production_incident_catalog,
)
from novel_flywheel.recovery_engine import FailureClass, ReliabilityFailure


@pytest.mark.parametrize(("message", "family"), (
    (
        "planning event facet receipt invalid: evidence_quote_unbound",
        "planning.review_evidence_binding_invalid",
    ),
    (
        "characters\\hua-sui.md missing location backlink to shen-fu-zhang-fang",
        "initialization.location_backlink_missing",
    ),
    (
        "characters\\hua-sui.md references missing location zhen-zi-ji-shi",
        "initialization.location_reference_missing",
    ),
    (
        "relationship love-interest expects backlink type love-interest, got rival",
        "initialization.relationship_inverse_mismatch",
    ),
    (
        "ConnectError (provider returned no error detail); All connection attempts failed",
        "provider.connection_failed",
    ),
    (
        "protocol_route_provider_rejection",
        "provider.route_rejected",
    ),
    (
        "HTTP 403 Forbidden from a configured route before terminal response",
        "provider.route_rejected",
    ),
    (
        "Controlled runtime ended without required tool output",
        "runtime.required_tool_output_missing",
    ),
    (
        "runtime fingerprint mismatch: active console is a stale process for the same data directory",
        "runtime.stale_console_process",
    ),
    (
        "[Errno 22] Invalid argument",
        "runtime.primary_error_masked",
    ),
    (
        "list index out of range",
        "parser.generated_artifact_shape",
    ),
    (
        "planning_packet_summary_authority_missing: beam_plan summary cannot bind retained body",
        "parser.generated_artifact_shape",
    ),
    (
        "planning_packet_protocol_exhausted: planning packet protocol recovery exhausted",
        "parser.generated_artifact_shape",
    ),
    (
        "规划适配回执没有用当前规划原文中的具体问题句证明负面判断",
        "planning.review_evidence_semantic_mismatch",
    ),
    (
        "规划第 2 段分包审核回执无效：evidence_binding，规划适配回执没有绑定当前规划段的准确原文",
        "planning.review_evidence_binding_invalid",
    ),
    (
        '规划第 6 段分包审核回执无效：[{"code":"adaptation_order_uncertain"}]',
        "planning.review_protocol_route_exhausted",
    ),
    (
        "规划稿未通过设定和分段检查，尚未生成正文",
        "planning.plan_structure_validation_failed",
    ),
    (
        "input context overflow preflight: lossless story authority plus output reserve requires 31537 tokens for context window 32768; topology=split",
        "model.context_capacity_preflight",
    ),
    (
        "input context overflow preflight: lossless story authority plus output reserve requires 27242 tokens for context window 32768; topology=compact；规划第 1 段单个事件不可再拆分，已保留完整事件权威",
        "model.context_capacity_indivisible_scope",
    ),
    (
        "单事件审核窗口回执未绑定完整范围或原文哈希",
        "planning.runtime_identity_echo_mismatch",
    ),
    (
        'planning receipt invalid: [{"code":"adaptation_receipt_conflict",'
        '"model_classification":"equivalent",'
        '"described_structural_dimensions":["entry_state","exit_state"],'
        '"raw_changed_dimensions":["entry_state","exit_state"]}]',
        "planning.reviewed_dimensions_echo_conflict",
    ),
    (
        "规划第 6 段事件 EV-A42514C2 的 function 分层审核回执无效："
        '["invariant_shape"]',
        "planning.invariant_truth_set_shape",
    ),
    (
        "规划执行索引未通过分段与整篇语义检查，尚未生成正文"
        "（issue_codes=adjacent_boundary_mismatch）",
        "planning.execution_manifest_handoff_echo_mismatch",
    ),
    (
        "finish_reason=max_tokens，模型输出字段截断",
        "model.output_truncated",
    ),
    (
        "短篇因果链解析失败，因果链未覆盖全部正式事件",
        "planning.causal_chain_invalid",
    ),
    (
        "规划调整改变了正式剧情方向或结局承诺",
        "planning.structure_drift",
    ),
    (
        "未修改第 3 段的潜伏旧问题被误归因给第 2 段修复候选",
        "planning.recovery_latent_issue_misattributed",
    ),
    (
        "规划正式事件缺少足以核对执行者、动作和结果的正文（EV-A42514C2）",
        "planning.event_body_integrity",
    ),
    (
        "planning_required_participant_missing：正式复合事件遗漏参与者、回应者或承诺方",
        "planning.event_obligation_incomplete",
    ),
    (
        "planning capacity split returned an incomplete artifact",
        "planning.packet_merge_closedness",
    ),
    (
        "event_body_collapsed: planning repair anchor collapsed a complete event",
        "planning.repair_anchor_collapse",
    ),
    (
        "narrator_confirmation_required: first-person narrator is ambiguous",
        "narrative.first_person_contract_missing",
    ),
    (
        "原子节拍不属于当前事件",
        "planning.atomic_beat_scope_mismatch",
    ),
    (
        "正文第 4/6 段仍有越界、重复或正文异常",
        "draft.segment_integrity_failed",
    ),
    (
        "自动拆分后的正文段没有通过检查：明显超过约 1083 字的范围",
        "draft.split_merge_length_mismatch",
    ),
    (
        "正文语义完整性检查未通过：semantic receipt exit state is not satisfied",
        "draft.semantic_receipt_unsatisfied",
    ),
    (
        "正在精简要求后重新润色本段，精修无法通过本地验证",
        "polish.local_validation_failed",
    ),
    (
        "同一问题 ID 出现在两个窗口时只保留第一份证据",
        "review.issue_ledger_not_refreshed",
    ),
    (
        "终审暂时不可用，可以稍后重试",
        "review.final_review_unavailable",
    ),
))
def test_historical_production_failures_have_stable_families(message, family) -> None:
    incident = classify_production_failure(
        message, workflow="short-story", stage="draft",
    )

    assert incident["incident_family"] == family


def test_typed_failure_classification_precedes_message_regex() -> None:
    failure = ReliabilityFailure(
        "receipt_schema", FailureClass.SYNTAX_PROTOCOL,
        "planning-review", unit_id="segment-5", protocol_only=True,
    )

    result = classify_production_failure(
        "completely novel wording without a known regex",
        workflow="short-story", stage="planning", failure=failure,
    )

    assert result["incident_family"] == "parser.generated_artifact_shape"
    assert result["failure_code"] == "receipt_schema"
    assert result["failure_class"] == "syntax_protocol"
    assert result["failure_unit_id"] == "segment-5"


def test_reviewed_dimensions_echo_incident_has_bounded_recovery_contract() -> None:
    incident = classify_production_failure(
        "planning_adaptation_reviewed_dimensions_echo",
        workflow="short-story", stage="planning",
    )

    assert incident["incident_family"] == (
        "planning.reviewed_dimensions_echo_conflict"
    )
    assert "derive structural deviations only from explicit false invariants" in (
        incident["known_resolution"]
    )
    assert "free-form dimensions" in incident["known_resolution"]
    assert "never rewrites planning or prose" in incident["known_resolution"]


def test_manifest_handoff_incident_has_runtime_authority_contract() -> None:
    incident = classify_production_failure(
        "adjacent_boundary_mismatch",
        workflow="short-story", stage="planning",
    )

    assert incident["incident_family"] == (
        "planning.execution_manifest_handoff_echo_mismatch"
    )
    assert "Runtime-owned authority" in incident["known_resolution"]
    assert "retaining the model's additional entry assertions" in (
        incident["known_resolution"]
    )
    assert "unchanged fragment, adjacent-boundary, and whole-manifest" in (
        incident["known_resolution"]
    )
    assert "Do not normalize malformed entry-state containers" in (
        incident["known_resolution"]
    )


def test_invariant_truth_set_incident_has_closed_conversion_contract() -> None:
    incident = classify_production_failure(
        "facet invariant_shape",
        workflow="short-story", stage="review",
    )

    assert incident["incident_family"] == "planning.invariant_truth_set_shape"
    assert "every requested invariant name exactly once" in (
        incident["known_resolution"]
    )
    assert "partial, duplicate, unknown" in incident["known_resolution"]
    assert "dedicated immutable-receipt system contract" in (
        incident["known_resolution"]
    )
    assert "must not be adapted" in incident["known_resolution"]
    assert "Historical checkpoints remain strict" in incident["known_resolution"]
    assert "unchanged whole-plan validator" in incident["known_resolution"]


def test_plan_structure_incident_separates_event_from_causal_companion() -> None:
    incident = classify_production_failure(
        "规划稿未通过设定和分段检查，尚未生成正文",
        workflow="short-story", stage="planning",
    )

    assert incident["incident_family"] == "planning.plan_structure_validation_failed"
    assert "事件实现与独立的因果关系说明" in incident["known_resolution"]
    assert "保留全部源文本" in incident["known_resolution"]
    assert "身份歧义或正文不完整" in incident["known_resolution"]


@pytest.mark.parametrize("message", [
    "HTTP 413 context_length_exceeded: prompt is too long",
    "maximum context length exceeded",
])
def test_provider_reported_context_overflow_uses_capacity_incident_family(
    message: str,
) -> None:
    incident = classify_production_failure(
        message, workflow="short-story", stage="planning",
    )

    assert incident["incident_family"] == "model.context_capacity_preflight"
    assert "供应商实际返回" in incident["known_resolution"]
    assert "splitter" in incident["known_resolution"]
    assert incident["known_resolution"]


def test_beam_summary_incident_resolution_preserves_complete_event_authority() -> None:
    incident = classify_production_failure(
        "event_body_collapsed after a beam_plan obligation summary",
        workflow="short-story", stage="planning",
    )

    assert incident["incident_family"] == "planning.repair_anchor_collapse"
    assert "beam_plan" in incident["known_resolution"]
    assert "complete accepted plan" in incident["known_resolution"]
    assert "whole-plan validation" in incident["known_resolution"]


def test_missing_provider_credentials_are_classified_separately_from_story_drift() -> None:
    incident = classify_production_failure(
        "主模型失败：missing_api_key: primary; 备用模型失败：missing_api_key: fallback",
        workflow="short-story", stage="planning",
    )

    assert incident["incident_family"] == "provider.credentials_unavailable"
    assert "active console data directory" in incident["known_resolution"]


def test_provider_credentials_production_fixture_preserves_recovery_contract() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" /
         "provider_credentials_unavailable_20260805.json").read_text(
             encoding="utf-8",
         )
    )
    incident = classify_production_failure(
        fixture["raw_error"],
        workflow=fixture["workflow"],
        stage=fixture["stage"],
    )

    assert incident["incident_family"] == fixture["incident_family"]
    assert fixture["expected_behavior"]["retain_best_plan"] is True
    assert fixture["expected_behavior"]["do_not_classify_as"] != incident[
        "incident_family"
    ]


def test_causal_packet_credentials_fixture_preserves_route_root_cause() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" /
         "causal_packet_credentials_unavailable_20260809.json").read_text(
             encoding="utf-8",
         )
    )
    incident = classify_production_failure(
        fixture["raw_error"],
        workflow=fixture["workflow"],
        stage=fixture["stage"],
    )

    assert incident["incident_family"] == fixture["incident_family"]
    assert fixture["expected_behavior"]["preserve_primary_error"] is True
    assert fixture["expected_behavior"]["preserve_fallback_error"] is True
    assert fixture["expected_behavior"]["do_not_classify_as"] != incident[
        "incident_family"
    ]


def test_stale_console_fixture_requires_fresh_runtime_without_killing_old_process() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" /
         "runtime_stale_console_20260805.json").read_text(encoding="utf-8")
    )
    incident = classify_production_failure(
        fixture["message"], workflow=fixture["workflow"], stage=fixture["stage"],
    )

    assert incident["incident_family"] == fixture["incident_family"]
    assert fixture["expected_behavior"]["reuse_old_process"] is False
    assert fixture["expected_behavior"]["kill_old_process"] is False
    assert "runtime fingerprint" in incident["known_resolution"]


def test_generated_packet_shape_fixture_preserves_local_recovery_contract() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" /
         "planning_packet_bold_heading_0ce8e2d3.json").read_text(
             encoding="utf-8",
         )
    )
    incident = classify_production_failure(
        fixture["terminal_error"], workflow="short-story", stage=fixture["stage"],
    )

    assert incident["incident_family"] == "parser.generated_artifact_shape"
    assert fixture["provider_finish_reason"] == "end_turn"
    assert fixture["transport_complete"] is True
    assert "validate the expected artifact count before indexing" in incident[
        "known_resolution"
    ].lower()


def test_generated_markdown_field_fixture_reuses_shape_incident_family() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" /
         "planning_packet_markdown_fields_0ce8e2d3.json").read_text(
             encoding="utf-8",
         )
    )

    incident = classify_production_failure(
        fixture["terminal_error"],
        workflow="short-story",
        stage=fixture["stage"],
    )

    assert incident["incident_family"] == fixture["incident_family"]
    assert fixture["provider_finish_reason"] == "end_turn"
    assert fixture["transport_complete"] is True
    assert "exact field or contract failures" in incident["known_resolution"]


def test_generated_event_array_and_segment_only_reuse_shape_incident_family() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" /
         "planning_packet_event_array_and_segment_only_0ce8e2d3.json").read_text(
             encoding="utf-8",
         )
    )
    incident = classify_production_failure(
        "planning repair packet JSON event array has ambiguous ordered event ownership",
        workflow="short-story",
        stage=fixture["stage"],
    )

    assert incident["incident_family"] == "parser.generated_artifact_shape"
    assert "top-level event array" in incident["known_resolution"]


def test_open_world_planning_wrappers_reuse_shape_incident_family() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" /
         "planning_packet_open_world_shapes_28da9961.json").read_text(
             encoding="utf-8",
         )
    )

    for message in fixture["terminal_errors"]:
        incident = classify_production_failure(
            message, workflow="short-story", stage=fixture["stage"],
        )
        assert incident["incident_family"] == fixture["incident_family"]
        assert "open presentation set" in incident["known_resolution"]
        assert "unknown machine-control fields" in incident["known_resolution"]

    assert fixture["provider_finish_reason"] == "end_turn"
    assert fixture["transport_complete"] is True


def test_unknown_incidents_normalize_volatile_ids_without_collapsing_other_causes() -> None:
    first = classify_production_failure(
        "Unexpected verifier 019f9b064a4f7422 failed in segment-4 with 900 characters",
        workflow="short-story", stage="review",
    )
    same = classify_production_failure(
        "Unexpected verifier 88ff9b064a4f7422 failed in segment-9 with 1200 characters",
        workflow="short-story", stage="review",
    )
    different = classify_production_failure(
        "Unexpected manifest checksum mismatch",
        workflow="short-story", stage="review",
    )

    assert first["incident_key"] == same["incident_key"]
    assert first["incident_key"] != different["incident_key"]


def test_read_time_incident_upgrade_refines_known_legacy_unclassified_family() -> None:
    legacy = {
        "message": (
            "规划第 2 段分包审核回执无效：evidence_binding，"
            "规划适配回执没有绑定当前规划段的准确原文"
        ),
        "workflow": "short-story",
        "stage": "planning",
        "current_stage": "planning",
        "metadata_json": json.dumps({
            "incident_key": "short-story:planning:unclassified.legacy",
            "incident_family": "unclassified.legacy",
            "incident_title": "尚未归类的生产失败",
        }, ensure_ascii=False),
    }

    metadata = Database._incident_metadata(legacy)

    assert metadata["incident_family"] == (
        "planning.review_evidence_binding_invalid"
    )
    assert metadata["legacy_incident_family"] == "unclassified.legacy"
    assert metadata["legacy_incident_key"].endswith("unclassified.legacy")


def test_catalog_exposes_every_registered_family_once() -> None:
    families = [item["incident_family"] for item in production_incident_catalog()]

    assert len(families) == len(set(families))
    assert "initialization.location_backlink_missing" in families
    assert "planning.structure_drift" in families
    assert "planning.recovery_latent_issue_misattributed" in families
    assert "planning.event_body_integrity" in families
    assert "planning.presentation_normalized_ownership_revealed" in families
    assert "planning.event_obligation_incomplete" in families
    assert "planning.participant_identity_realization_mismatch" in families
    assert "polish.local_validation_failed" in families
    assert "planning.repair_anchor_collapse" in families
    assert "narrative.first_person_contract_missing" in families
    assert "runtime.stale_console_process" in families
    assert "parser.generated_artifact_shape" in families


def test_recorded_field_table_incident_is_stage_progress_not_parser_regression() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "planning_field_table_4e79a0f4.json")
        .read_text(encoding="utf-8")
    )

    incident = classify_production_failure(
        "规划表格已经本地规范化，并发现 29 个正式事件正文归属问题",
        workflow="short-story",
        stage="planning",
    )

    assert fixture["source_artifact_sha256"]
    assert incident["incident_family"] == (
        "planning.presentation_normalized_ownership_revealed"
    )
    assert "更晚验证阶段" in incident["known_resolution"]
    assert "其他分段" in incident["known_resolution"]


def test_planning_structure_incident_resolution_forbids_cross_segment_rollback() -> None:
    incident = classify_production_failure(
        "规划恢复尚未收敛，最佳候选和有效上游进度已保留",
        workflow="short-story", stage="planning",
    )

    assert incident["incident_family"] == "planning.structure_drift"
    assert "逐段修复" in incident["known_resolution"]
    assert "某段失败不得撤销其他已通过段" in incident["known_resolution"]


def test_nested_creative_heading_is_classified_as_typed_ir_scope_collision() -> None:
    incident = classify_production_failure(
        "Nested narrative heading was mistaken for a Runtime handoff control field",
        workflow="short-story", stage="planning",
    )

    assert incident["incident_family"] == "planning.typed_ir_scope_collision"
    assert "content-addressed planning IR" in incident["known_resolution"]
    assert "complete-draft" in incident["known_resolution"]


def test_planning_repair_anchor_production_fixture_is_classified_and_recoverable() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "planning_repair_anchor_collapse_de3131b3.json")
        .read_text(encoding="utf-8")
    )

    incident = classify_production_failure(
        fixture["message"], workflow=fixture["workflow"], stage=fixture["stage"],
    )

    assert incident["incident_family"] == fixture["incident_family"]
    assert "exact nested" in incident["known_resolution"]


def test_real_planning_event_body_fixture_is_classified_and_recoverable() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "planning_event_body_shared_scope_d6d16a84.json")
        .read_text(encoding="utf-8")
    )

    incident = classify_production_failure(
        fixture["message"], workflow=fixture["workflow"], stage=fixture["stage"],
    )

    assert incident["incident_family"] == fixture["incident_family"]
    assert "相邻事件 ID" in incident["known_resolution"]


def test_real_planning_event_obligation_fixture_has_executable_recovery() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" /
         "planning_event_obligation_incomplete_9946d29b.json")
        .read_text(encoding="utf-8")
    )

    incident = classify_production_failure(
        fixture["message"], workflow=fixture["workflow"], stage=fixture["stage"],
    )

    assert incident["incident_family"] == fixture["incident_family"]
    assert "事件完成清单" in incident["known_resolution"]
    assert "哈希绑定" in incident["known_resolution"]
    assert "来源不唯一" in incident["known_resolution"]
    assert "只重建所属完整正式段" in incident["known_resolution"]
    assert "不消耗语义修复次数" in incident["known_resolution"]
    assert "相邻边界和整篇审核" in incident["known_resolution"]


def test_first_person_participant_identity_fixture_has_contract_driven_recovery() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" /
         "planning_first_person_participant_identity_5bb4b703.json")
        .read_text(encoding="utf-8")
    )

    incident = classify_production_failure(
        fixture["message"], workflow="short-story", stage="planning",
    )

    assert incident["incident_family"] == fixture["incident_family"]
    assert "项目叙事契约" in incident["known_resolution"]
    assert "非对白叙事声部" in incident["known_resolution"]
    assert "未知别名" in incident["known_resolution"]
    assert "整篇因果链" in incident["known_resolution"]


def test_context_capacity_production_fixture_is_classified_and_recoverable() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "context_capacity_dd0d6d2d.json")
        .read_text(encoding="utf-8")
    )

    incident = classify_production_failure(
        fixture["message"],
        workflow=fixture["workflow"],
        stage=fixture["stage"],
    )

    assert incident["incident_family"] == fixture["incident_family"]
    assert "分包" in incident["known_resolution"]


def test_review_evidence_mismatch_production_fixture_is_protocol_only() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" /
         "planning_review_evidence_semantic_mismatch_13ab5b72.json")
        .read_text(encoding="utf-8")
    )

    incident = classify_production_failure(
        fixture["message"],
        workflow=fixture["workflow"],
        stage=fixture["stage"],
    )

    assert incident["incident_family"] == fixture["incident_family"]
    assert "不消耗规划修复预算" in incident["known_resolution"]


def test_latent_issue_attribution_production_fixture_has_granular_resolution() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" /
         "planning_latent_issue_attribution_62859567.json")
        .read_text(encoding="utf-8")
    )

    incident = classify_production_failure(
        fixture["message"],
        workflow=fixture["workflow"],
        stage=fixture["stage"],
    )

    assert incident["incident_family"] == fixture["incident_family"]
    assert "实际分段哈希" in incident["known_resolution"]
    assert "后续独立修复单元" in incident["known_resolution"]
