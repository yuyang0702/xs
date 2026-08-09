from __future__ import annotations

import copy
from dataclasses import asdict
import hashlib
import json

import pytest

from novel_flywheel.execution_manifest import (
    ShortExecutionManifest,
    bind_execution_manifest_receipt_evidence,
    execution_manifest_issues,
    execution_manifest_payload,
    execution_manifest_receipt_issues,
    execution_manifest_receipt_binding_issues,
    execution_manifest_receipt_issues_are_protocol_only,
    execution_manifest_sha256,
    legacy_execution_index_requires_rebuild,
    merge_execution_manifest_fragments,
    parse_execution_manifest,
    state_assertions_sha256,
    validate_execution_manifest_receipt,
)


AUTHORITY = {
    "authority_sha256": "a" * 64,
    "outline_sha256": "b" * 64,
    "planning_sha256": "c" * 64,
    "causal_chain_sha256": "d" * 64,
}


def manifest_payload() -> dict:
    payload = {
        "version": 2,
        "status": "ready",
        **AUTHORITY,
        "beats": [
            {
                "beat_id": "EV-9D165428/01",
                "source_event_id": "EV-9D165428",
                "order": 1,
                "action": "裴砚行向沈老夫人提出核实身份",
                "preconditions": ["裴砚行已经观察花穗的席间举止"],
                "postconditions": ["沈老夫人决定核实身份"],
                "owner_segment": 1,
                "source_evidence": "饭后向沈老夫人进言：此女举止粗鄙，来历需严查",
            },
            {
                "beat_id": "EV-8E4BBA17/01",
                "source_event_id": "EV-8E4BBA17",
                "order": 2,
                "action": "沈老夫人派人外出核实花穗身份",
                "preconditions": ["沈老夫人决定核实身份"],
                "postconditions": ["核实身份的人已经出发", "花穗的时间窗口开始收紧"],
                "owner_segment": 1,
                "source_evidence": "沈老夫人派人去核实花穗身份",
            },
            {
                "beat_id": "EV-8E4BBA17/02",
                "source_event_id": "EV-8E4BBA17",
                "order": 3,
                "action": "花穗发现二十两在她入府前已经支出",
                "preconditions": ["花穗经过账房后窗"],
                "postconditions": ["花穗确认误认是人为安排"],
                "owner_segment": 2,
                "source_evidence": "沈家账房最近支出一笔银两，数目恰好是二十两",
            },
        ],
        "segments": [
            {
                "segment": 1,
                "beat_ids": ["EV-9D165428/01", "EV-8E4BBA17/01"],
                "entry_state": [
                    {"state": "故事开篇", "inherited_from": "opening"},
                ],
                "exit_state": [
                    {
                        "state": "核实身份的人已经出发",
                        "produced_by": "EV-8E4BBA17/01",
                    },
                    {
                        "state": "花穗的时间窗口开始收紧",
                        "produced_by": "EV-8E4BBA17/01",
                    },
                ],
                "previous_exit_sha256": "",
                "prohibited_future_beat_ids": ["EV-8E4BBA17/02"],
            },
            {
                "segment": 2,
                "beat_ids": ["EV-8E4BBA17/02"],
                "entry_state": [
                    {
                        "state": "核实身份的人已经出发",
                        "inherited_from": "segment-01",
                    },
                    {
                        "state": "花穗的时间窗口开始收紧",
                        "inherited_from": "segment-01",
                    },
                ],
                "exit_state": [
                    {
                        "state": "花穗确认误认是人为安排",
                        "produced_by": "EV-8E4BBA17/02",
                    },
                ],
                "previous_exit_sha256": "pending",
                "prohibited_future_beat_ids": [],
            },
        ],
        "semantic_receipt": {
            "authority_sha256": "a" * 64,
            "manifest_sha256": "pending",
            "valid": True,
        },
        "repair_attempts": 0,
    }
    payload["segments"][1]["previous_exit_sha256"] = hashlib.sha256(
        json.dumps(
            [{
                "state": item["state"],
                "produced_by": item.get("produced_by", ""),
                "inherited_from": item.get("inherited_from", ""),
            } for item in payload["segments"][0]["exit_state"]], ensure_ascii=False,
            sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return payload


def validate(payload: dict) -> list[dict]:
    manifest = parse_execution_manifest(payload)
    return execution_manifest_issues(
        manifest,
        expected_event_ids=["EV-9D165428", "EV-8E4BBA17"],
        segment_count=2,
        authority_hashes=AUTHORITY,
    )


def test_atomic_beats_allow_one_formal_event_to_cross_segments_without_shared_ownership() -> None:
    payload = manifest_payload()

    assert validate(payload) == []
    assert len(execution_manifest_sha256(parse_execution_manifest(payload))) == 64


def test_v2_manifest_hash_omits_v3_optional_fields_for_saved_receipt_compatibility() -> None:
    payload = manifest_payload()
    manifest = parse_execution_manifest(payload)
    old_payload = asdict(manifest)
    old_payload.pop("semantic_receipt")
    for beat in old_payload["beats"]:
        for field in (
            "presentation_order", "story_time", "timeline", "actor",
            "location", "viewpoint", "knowledge_delta", "relationship_delta",
        ):
                beat.pop(field)
    for segment in old_payload["segments"]:
            for assertion in segment["entry_state"] + segment["exit_state"]:
                producers = assertion["produced_by"]
                assertion["produced_by"] = producers[0] if producers else ""
                assertion.pop("claim")
    expected = hashlib.sha256(json.dumps(
        old_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()

    assert execution_manifest_sha256(manifest) == expected


def test_v5_state_assertion_round_trips_a_typed_narrative_claim() -> None:
    payload = manifest_payload()
    payload["version"] = 5
    for segment in payload["segments"]:
        for assertion in segment["entry_state"] + segment["exit_state"]:
            produced_by = assertion.get("produced_by")
            assertion["produced_by"] = [produced_by] if produced_by else []
    payload["segments"][0]["exit_state"][0]["claim"] = {
        "claim_id": "identity-revealed",
        "subject": "花穗",
        "predicate": "identity.actual",
        "value": "花穗",
        "perspective": "public",
        "status": "known",
        "transition": "reveal",
        "authority": "formal",
        "event_id": "EV-8E4BBA17",
        "event_order": 2,
        "evidence": "花穗公开坦白",
    }

    manifest = parse_execution_manifest(payload)
    serialized = execution_manifest_payload(manifest)

    claim = manifest.segments[0].exit_state[0].claim
    assert claim is not None and claim.predicate == "identity.actual"
    assert serialized["segments"][0]["exit_state"][0]["claim"]["claim_id"] == "identity-revealed"


def test_exit_state_cannot_be_produced_by_a_beat_owned_by_the_next_segment() -> None:
    payload = manifest_payload()
    payload["beats"][1]["owner_segment"] = 2
    payload["segments"][0]["beat_ids"] = ["EV-9D165428/01"]
    payload["segments"][1]["beat_ids"] = [
        "EV-8E4BBA17/01", "EV-8E4BBA17/02",
    ]

    issues = validate(payload)

    assert {
        "code": "exit_producer_not_owned",
        "segment": 1,
        "beat_id": "EV-8E4BBA17/01",
        "message": "第 1 段出口状态由其他段负责的节拍产生",
    } in issues


def test_new_exit_state_requires_an_owned_producer() -> None:
    payload = manifest_payload()
    payload["segments"][0]["exit_state"][0].pop("produced_by")

    issues = validate(payload)

    assert any(item["code"] == "exit_producer_missing" for item in issues)


def test_segment_must_prohibit_the_exact_later_beat_set() -> None:
    payload = manifest_payload()
    payload["segments"][0]["prohibited_future_beat_ids"] = []

    issues = validate(payload)

    assert any(item["code"] == "future_beat_prohibition_mismatch" for item in issues)


def test_manifest_reports_all_independent_ownership_and_boundary_failures() -> None:
    payload = manifest_payload()
    payload["beats"][1]["owner_segment"] = 2
    payload["segments"][0]["beat_ids"].append("EV-8E4BBA17/02")
    payload["segments"][1]["entry_state"][0]["state"] = "核实身份的人尚未出发"

    codes = {item["code"] for item in validate(payload)}

    assert {
        "beat_owner_mismatch",
        "duplicate_segment_beat",
        "exit_producer_not_owned",
        "adjacent_boundary_mismatch",
    } <= codes


def test_adjacent_segment_must_bind_exact_previous_exit_hash() -> None:
    payload = manifest_payload()
    payload["segments"][1]["previous_exit_sha256"] = "f" * 64

    issues = validate(payload)

    assert any(item["code"] == "previous_exit_hash_mismatch" for item in issues)


@pytest.mark.parametrize("value", [None, {}, {"version": 1}, {"version": "2"}])
def test_legacy_or_unversioned_execution_indexes_require_rebuild(value: object) -> None:
    assert legacy_execution_index_requires_rebuild(value) is True


def test_v2_manifest_remains_readable_but_requires_v3_rebuild() -> None:
    payload = manifest_payload()

    assert parse_execution_manifest(payload).version == 2
    assert legacy_execution_index_requires_rebuild(payload) is True


def test_current_v3_manifest_does_not_require_rebuild() -> None:
    payload = manifest_payload()
    payload["version"] = 3

    assert legacy_execution_index_requires_rebuild(payload) is False


def test_current_v4_manifest_does_not_require_rebuild() -> None:
    payload = manifest_payload()
    payload["version"] = 4
    for segment in payload["segments"]:
        for assertion in segment["exit_state"]:
            assertion["produced_by"] = [assertion["produced_by"]]

    assert legacy_execution_index_requires_rebuild(payload) is False


def test_v3_scalar_producer_round_trip_is_idempotent_and_hash_stable() -> None:
    payload = manifest_payload()
    payload["version"] = 3
    manifest = parse_execution_manifest(payload)

    first = execution_manifest_payload(manifest)
    reparsed = parse_execution_manifest(first)
    second = execution_manifest_payload(reparsed)

    assert first == second
    assert execution_manifest_sha256(reparsed) == execution_manifest_sha256(manifest)
    assert isinstance(first["segments"][0]["exit_state"][0]["produced_by"], str)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("EV-9D165428/01", ("EV-9D165428/01",)),
        (
            "EV-9D165428/01， EV-8E4BBA17/01",
            ("EV-9D165428/01", "EV-8E4BBA17/01"),
        ),
        (
            ["EV-9D165428/01", "EV-8E4BBA17/01"],
            ("EV-9D165428/01", "EV-8E4BBA17/01"),
        ),
    ],
)
def test_v4_normalizes_single_list_and_delimited_multi_producers(
    value: object, expected: tuple[str, ...],
) -> None:
    payload = manifest_payload()
    payload["version"] = 4
    payload["segments"][0]["exit_state"][0]["produced_by"] = value

    assertion = parse_execution_manifest(payload).segments[0].exit_state[0]

    assert assertion.produced_by == expected


def test_v4_rejects_non_beat_producer_labels() -> None:
    payload = manifest_payload()
    payload["version"] = 4
    payload["segments"][0]["exit_state"][0]["produced_by"] = "narrative_overview"

    with pytest.raises(ValueError, match="must use EV-XXXXXXXX/NN"):
        parse_execution_manifest(payload)


def test_parser_rejects_duplicate_beat_ids_before_workflow_use() -> None:
    payload = manifest_payload()
    payload["beats"].append(copy.deepcopy(payload["beats"][0]))

    with pytest.raises(ValueError, match="duplicate beat_id"):
        parse_execution_manifest(payload)


def semantic_receipt(payload: dict, authority_text: str) -> dict:
    manifest = parse_execution_manifest(payload)
    return {
        "authority_sha256": manifest.authority_sha256,
        "manifest_sha256": execution_manifest_sha256(manifest),
        "beat_receipts": [
            {
                "beat_id": beat.beat_id,
                "evidence": beat.source_evidence,
                "actor_action_valid": True,
            }
            for beat in manifest.beats
        ],
        "segment_receipts": [
            {
                "segment": segment.segment,
                "boundary_valid": True,
                "evidence": segment.exit_state[0].state,
            }
            for segment in manifest.segments
        ],
        "formal_plot_unchanged": True,
        "summary": "节拍动作、所有权与相邻边界均符合正式资料。",
    }


def manifest_authority_text(payload: dict) -> str:
    return "\n".join([
        *(beat["source_evidence"] for beat in payload["beats"]),
        *(
            assertion["state"]
            for segment in payload["segments"]
            for assertion in segment["exit_state"]
        ),
    ])


def test_semantic_receipt_binds_every_beat_and_segment_to_exact_authority() -> None:
    payload = manifest_payload()
    authority_text = manifest_authority_text(payload)

    receipt = validate_execution_manifest_receipt(
        parse_execution_manifest(payload),
        authority_text,
        semantic_receipt(payload, authority_text),
    )

    assert [item["beat_id"] for item in receipt["beat_receipts"]] == [
        item["beat_id"] for item in payload["beats"]
    ]


def test_semantic_receipt_rejects_evidence_not_present_in_authority() -> None:
    payload = manifest_payload()
    authority_text = manifest_authority_text(payload)
    receipt = semantic_receipt(payload, authority_text)
    receipt["beat_receipts"][1]["evidence"] = "规划和大纲都没有这句话"

    with pytest.raises(ValueError, match="beat evidence is not bound"):
        validate_execution_manifest_receipt(
            parse_execution_manifest(payload), authority_text, receipt,
        )


def test_runtime_binds_beat_and_formatted_segment_evidence_to_exact_authority() -> None:
    payload = manifest_payload()
    manifest = parse_execution_manifest(payload)
    exact_boundary = "**段末交接**：花穗确认误认是人为安排"
    authority_text = manifest_authority_text(payload) + "\n" + exact_boundary
    receipt = semantic_receipt(payload, authority_text)
    receipt["beat_receipts"][0]["evidence"] = "审核模型改写过的节拍证据"
    receipt["segment_receipts"][0].update({
        "evidence": "段末交接：\n- 花穗确认误认是人为安排",
    })

    bound = bind_execution_manifest_receipt_evidence(
        manifest, authority_text, receipt,
        segment_evidence_candidates={1: {"SEG-01-E001": exact_boundary}},
    )

    assert isinstance(bound, dict)
    assert bound["beat_receipts"][0]["evidence"] == (
        manifest.beats[0].source_evidence
    )
    assert bound["segment_receipts"][0]["evidence"] == exact_boundary
    assert execution_manifest_receipt_issues(manifest, authority_text, bound) == []


def test_receipt_protocol_classifier_separates_binding_from_semantic_failure() -> None:
    assert execution_manifest_receipt_issues_are_protocol_only([{
        "code": "receipt_segment_evidence_unbound",
    }]) is True
    assert execution_manifest_receipt_issues_are_protocol_only([{
        "code": "receipt_beat_actor_action",
    }]) is False


def test_semantic_receipt_rejects_stale_manifest_hash() -> None:
    payload = manifest_payload()
    authority_text = manifest_authority_text(payload)
    receipt = semantic_receipt(payload, authority_text)
    receipt["manifest_sha256"] = "f" * 64

    with pytest.raises(ValueError, match="manifest hash is stale"):
        validate_execution_manifest_receipt(
            parse_execution_manifest(payload), authority_text, receipt,
        )


def test_saved_manifest_receipt_must_remain_bound_to_exact_manifest() -> None:
    payload = manifest_payload()
    authority_text = manifest_authority_text(payload)
    payload["semantic_receipt"] = semantic_receipt(payload, authority_text)
    manifest = parse_execution_manifest(payload)

    assert execution_manifest_receipt_binding_issues(manifest) == []

    payload["semantic_receipt"]["beat_receipts"] = payload[
        "semantic_receipt"
    ]["beat_receipts"][:-1]
    issues = execution_manifest_receipt_binding_issues(
        parse_execution_manifest(payload),
    )
    assert any(item["code"] == "receipt_beat_coverage" for item in issues)


def test_manifest_evidence_must_belong_to_its_declared_event_contract() -> None:
    payload = manifest_payload()
    payload["beats"][0]["source_evidence"] = payload["beats"][1]["source_evidence"]
    manifest = parse_execution_manifest(payload)

    issues = execution_manifest_issues(
        manifest,
        expected_event_ids=["EV-9D165428", "EV-8E4BBA17"],
        segment_count=2,
        authority_hashes=AUTHORITY,
        expected_events=[
            {
                "id": "EV-9D165428",
                "evidence": "饭后向沈老夫人进言：此女举止粗鄙，来历需严查",
            },
            {
                "id": "EV-8E4BBA17",
                "evidence": (
                    "沈老夫人派人去核实花穗身份。"
                    "沈家账房最近支出一笔银两，数目恰好是二十两"
                ),
            },
        ],
    )

    assert any(item["code"] == "source_evidence_mismatch" for item in issues)


def test_semantic_receipt_reports_hash_actor_boundary_and_plot_errors_together() -> None:
    payload = manifest_payload()
    authority_text = manifest_authority_text(payload)
    receipt = semantic_receipt(payload, authority_text)
    receipt.update({
        "authority_sha256": "f" * 64,
        "manifest_sha256": "e" * 64,
        "formal_plot_unchanged": False,
    })
    receipt["beat_receipts"][0]["actor_action_valid"] = False
    receipt["segment_receipts"][0]["boundary_valid"] = False

    codes = {
        item["code"] for item in execution_manifest_receipt_issues(
            parse_execution_manifest(payload), authority_text, receipt,
        )
    }

    assert {
        "receipt_authority_hash", "receipt_manifest_hash",
        "receipt_beat_actor_action", "receipt_segment_boundary",
        "receipt_formal_plot",
    } <= codes


def test_semantic_receipt_preserves_field_level_failure_diagnostics() -> None:
    payload = manifest_payload()
    authority_text = manifest_authority_text(payload)
    receipt = semantic_receipt(payload, authority_text)
    receipt["beat_receipts"][0].update({
        "actor_action_valid": False,
        "invalid_fields": ["location", "knowledge_delta"],
        "reason": "地点和人物判断没有正式资料依据",
    })

    issue = next(
        item for item in execution_manifest_receipt_issues(
            parse_execution_manifest(payload), authority_text, receipt,
        )
        if item["code"] == "receipt_beat_actor_action"
    )

    assert issue["invalid_fields"] == ["location", "knowledge_delta"]
    assert issue["reason"] == "地点和人物判断没有正式资料依据"


def test_fragment_merge_rebinds_global_ids_order_handoffs_and_future_bans() -> None:
    first_payload = manifest_payload()
    first_payload["version"] = 3
    first_payload["status"] = "fragment_ready"
    first_payload["beats"] = first_payload["beats"][:2]
    first_payload["segments"] = first_payload["segments"][:1]
    first_payload["segments"][0]["prohibited_future_beat_ids"] = []
    second_payload = manifest_payload()
    second_payload["version"] = 3
    second_payload["status"] = "fragment_ready"
    second_payload["beats"] = [copy.deepcopy(second_payload["beats"][2])]
    second_payload["beats"][0].update({
        "beat_id": "EV-8E4BBA17/01", "order": 1,
        "presentation_order": 1,
    })
    second_payload["segments"] = [copy.deepcopy(second_payload["segments"][1])]
    first_fragment = parse_execution_manifest(first_payload)
    previous_exit_sha256 = state_assertions_sha256(
        first_fragment.segments[0].exit_state, version=3,
    )
    second_payload["segments"][0].update({
        "beat_ids": ["EV-8E4BBA17/01"],
        "previous_exit_sha256": previous_exit_sha256,
    })

    merged = merge_execution_manifest_fragments(
        [first_fragment, parse_execution_manifest(second_payload)],
        authority_hashes=AUTHORITY, segment_count=2,
    )

    assert isinstance(merged, ShortExecutionManifest)
    assert [beat.beat_id for beat in merged.beats] == [
        "EV-9D165428/01", "EV-8E4BBA17/01", "EV-8E4BBA17/02",
    ]
    assert [beat.order for beat in merged.beats] == [1, 2, 3]
    assert [beat.presentation_order for beat in merged.beats] == [1, 2, 3]
    assert merged.segments[0].prohibited_future_beat_ids == ("EV-8E4BBA17/02",)
    assert merged.version == 4
    assert merged.segments[1].previous_exit_sha256 == state_assertions_sha256(
        merged.segments[0].exit_state, version=4,
    )


def test_fragment_merge_preserves_and_rebinds_every_composite_producer() -> None:
    payload = manifest_payload()
    payload["version"] = 4
    payload["status"] = "fragment_ready"
    payload["beats"] = payload["beats"][:2]
    payload["segments"] = payload["segments"][:1]
    payload["segments"][0]["prohibited_future_beat_ids"] = []
    payload["segments"][0]["exit_state"][0]["produced_by"] = [
        "EV-9D165428/01", "EV-8E4BBA17/01",
    ]

    merged = merge_execution_manifest_fragments(
        [parse_execution_manifest(payload)],
        authority_hashes=AUTHORITY, segment_count=1,
    )

    assert merged.segments[0].exit_state[0].produced_by == (
        "EV-9D165428/01", "EV-8E4BBA17/01",
    )


def test_v3_optional_contract_supports_nonlinear_nonhuman_execution() -> None:
    payload = manifest_payload()
    payload["version"] = 3
    payload["beats"][0].update({
        "presentation_order": 1,
        "story_time": "灾变前三小时",
        "timeline": "轨道站时间线",
        "actor": "空间站自治系统",
        "location": "环月轨道站",
        "viewpoint": "受限第三人称",
        "knowledge_delta": ["值班员尚不知道系统已经接管气闸"],
        "relationship_delta": ["系统与乘员从协作转为对抗"],
    })

    beat = parse_execution_manifest(payload).beats[0]

    assert beat.actor == "空间站自治系统"
    assert beat.location == "环月轨道站"
    assert beat.story_time == "灾变前三小时"
    assert beat.timeline == "轨道站时间线"
    assert beat.knowledge_delta
    assert beat.relationship_delta
