from __future__ import annotations

import copy

import pytest

from novel_flywheel.execution_manifest import (
    execution_manifest_issues,
    execution_manifest_sha256,
    legacy_execution_index_requires_rebuild,
    parse_execution_manifest,
)


AUTHORITY = {
    "authority_sha256": "a" * 64,
    "outline_sha256": "b" * 64,
    "planning_sha256": "c" * 64,
    "causal_chain_sha256": "d" * 64,
}


def manifest_payload() -> dict:
    return {
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
                "previous_exit_sha256": "e" * 64,
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


@pytest.mark.parametrize("value", [None, {}, {"version": 1}, {"version": "2"}])
def test_legacy_or_unversioned_execution_indexes_require_rebuild(value: object) -> None:
    assert legacy_execution_index_requires_rebuild(value) is True


def test_current_manifest_does_not_require_rebuild() -> None:
    assert legacy_execution_index_requires_rebuild(manifest_payload()) is False


def test_parser_rejects_duplicate_beat_ids_before_workflow_use() -> None:
    payload = manifest_payload()
    payload["beats"].append(copy.deepcopy(payload["beats"][0]))

    with pytest.raises(ValueError, match="duplicate beat_id"):
        parse_execution_manifest(payload)
