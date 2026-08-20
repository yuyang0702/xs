from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.canary.provider_capability_probe_contract import (
    EXTERNAL_ACTION_COUNTERS,
    ProviderCapabilityProbeContractError,
    ProviderCapabilityProbeObservationV1,
    ProviderContentBlockMetadataV1,
    build_provider_capability_probe_definition_v1,
    build_provider_capability_probe_fixture_v1,
    build_provider_capability_probe_observation_v1,
    contract_artifacts_v1,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def definition():
    return build_provider_capability_probe_definition_v1(REPO_ROOT)


@pytest.fixture(scope="module")
def fixture(definition):
    return build_provider_capability_probe_fixture_v1(REPO_ROOT, definition)


def _observe(definition, fixture, *, blocks, finish="end_turn", **updates):
    values = {
        "output_tokens": 10,
        "effective_provider_max_output_tokens": None,
        "adapter_visible_characters": sum(
            item.get("visible_text_characters", 0) for item in blocks
            if item["block_type"] in {"text", "output_text"}
        ),
        "adapter_tool_arguments_present": any(
            item.get("tool_arguments_present", False) for item in blocks
        ),
        "parser_reached": True,
        "strict_tool_reached": False,
        "json_conversion_reached": False,
        "wire_schema_reached": False,
        "semantic_validation_reached": False,
    }
    values.update(updates)
    return build_provider_capability_probe_observation_v1(
        definition=definition,
        fixture=fixture,
        blocks=blocks,
        finish_reason=finish,
        **values,
    )


def test_planning_semantic_v2_fixture_is_exact_hash_bound(definition, fixture):
    assert definition.parent_evidence_status == "exact"
    assert definition.target.boundary == 12
    assert definition.target.contract_name == "planning_semantic_v2"
    assert definition.target.contract_version == 2
    assert definition.target.route_kind == "configured_fallback"
    assert definition.target.protocol == "anthropic"
    assert definition.target.execution_mode == "plain"
    assert definition.target.requested_max_output_tokens == 8798
    assert fixture.fixture_status == "exact_hash_bound"
    assert fixture.source_workload_sha256 == (
        "c2eff79242ff5a746ff263ff28639c950180ecc0565643e8ffebcdd8d16158d1"
    )
    assert fixture.target_boundary_identity_sha256 == definition.target.identity_sha256
    assert fixture.input_content_embedded is False


def test_fixture_fails_closed_when_sanitized_source_is_unavailable(
    definition, tmp_path,
):
    with pytest.raises(ProviderCapabilityProbeContractError) as exc:
        build_provider_capability_probe_fixture_v1(tmp_path, definition)
    assert exc.value.reason_code == "R1_PTR4_V1_PROBE_FIXTURE_NOT_AVAILABLE"


@pytest.mark.parametrize(
    ("blocks", "finish", "updates", "expected"),
    [
        ([{"block_type": "tool_use", "tool_arguments_present": True,
           "tool_argument_byte_length": 17}], "end_turn", {}, "TOOL_ONLY"),
        ([{"block_type": "text", "visible_text_characters": 80}],
         "max_tokens", {}, "TEXT_TRUNCATED"),
        ([{"block_type": "reasoning"}], "end_turn", {}, "REASONING_ONLY"),
        ([], "max_tokens", {}, "ZERO_VISIBLE_MAX_TOKENS"),
        ([{"block_type": "text", "visible_text_characters": 40}],
         "end_turn", {"adapter_visible_characters": 0},
         "ADAPTER_VISIBLE_CONTENT_LOSS"),
        ([{"block_type": "text", "visible_text_characters": 25},
          {"block_type": "tool_use", "tool_arguments_present": True,
           "tool_argument_byte_length": 19}],
         "max_tokens", {}, "MIXED_BLOCK_TRUNCATION"),
        ([{"block_type": "vendor_future_block"}],
         "end_turn", {}, "UNKNOWN"),
        ([{"block_type": "tool_use", "tool_arguments_present": True,
           "tool_argument_byte_length": 29, "partial_tool_arguments": True}],
         "max_tokens", {}, "TOOL_ARGUMENTS_TRUNCATED"),
    ],
)
def test_shape_classification_matrix(
    definition, fixture, blocks, finish, updates, expected,
):
    observation = _observe(
        definition, fixture, blocks=blocks, finish=finish, **updates,
    )
    assert observation.post_adapter.output_limit_classifier == expected
    assert observation.provider_capability_evidence_status == "fake_rehearsal_only"
    assert observation.external_action_counters == EXTERNAL_ACTION_COUNTERS


def test_post_adapter_lineage_records_every_required_boundary(definition, fixture):
    observation = _observe(
        definition,
        fixture,
        blocks=[{"block_type": "text", "visible_text_characters": 9}],
        parser_reached=True,
        json_conversion_reached=True,
        wire_schema_reached=True,
        semantic_validation_reached=True,
    )
    post = observation.post_adapter
    assert post.adapter_visible_text is True
    assert post.adapter_visible_characters == 9
    assert post.strict_tool_reached is False
    assert post.parser_reached is True
    assert post.json_conversion_reached is True
    assert post.wire_schema_reached is True
    assert post.semantic_validation_reached is True
    assert len(post.lineage_receipt_sha256) == 64


def test_privacy_contract_rejects_raw_fields_and_outputs_no_business_content(
    definition, fixture,
):
    with pytest.raises(ValueError):
        ProviderContentBlockMetadataV1.model_validate({
            "block_type": "text",
            "visible_text_characters": 3,
            "raw_text": "forbidden",
        })
    artifacts = contract_artifacts_v1(REPO_ROOT)
    serialized = json.dumps(artifacts, ensure_ascii=False, sort_keys=True)
    source = json.loads((REPO_ROOT / fixture.source_workload_file).read_text(
        encoding="utf-8"
    ))
    for field in ("title", "premise", "outline"):
        assert source[field] not in serialized
    assert '"raw_text":' not in serialized
    assert '"raw_provider_response":' not in serialized


def test_observation_schema_forbids_unregistered_raw_provider_content(
    definition, fixture,
):
    observation = _observe(definition, fixture, blocks=[])
    payload = observation.model_dump(mode="json", by_alias=True)
    payload["raw_provider_response"] = "forbidden"
    with pytest.raises(ValueError):
        ProviderCapabilityProbeObservationV1.model_validate(payload)


def test_external_actions_remain_zero(definition, fixture):
    artifacts = contract_artifacts_v1(REPO_ROOT)
    assert artifacts["definition"]["external_action_counters"] == (
        EXTERNAL_ACTION_COUNTERS
    )
    assert artifacts["observer_schema_bundle"]["external_action_counters"] == (
        EXTERNAL_ACTION_COUNTERS
    )
    observation = _observe(definition, fixture, blocks=[])
    assert all(value == 0 for value in observation.external_action_counters.values())


def test_materialized_definition_and_fixture_are_exact():
    artifacts = contract_artifacts_v1(REPO_ROOT)
    report_root = REPO_ROOT / "docs/superpowers/reports/r1-ptr4-v1"
    assert json.loads((
        report_root / "provider-capability-probe-definition-v1.json"
    ).read_text(encoding="utf-8")) == artifacts["definition"]
    assert json.loads((
        report_root / "provider-capability-probe-fixture-v1.json"
    ).read_text(encoding="utf-8")) == artifacts["fixture"]
    observer_identity = json.loads((
        report_root / "provider-capability-probe-observer-schema-identity-v1.json"
    ).read_text(encoding="utf-8"))
    assert observer_identity["observation_schema_sha256"] == (
        artifacts["definition"]["observer_schema_sha256"]
    )
    assert observer_identity["schema_bundle_sha256"] == (
        artifacts["observer_schema_bundle"]["bundle_sha256"]
    )
