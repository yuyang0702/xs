import json

import pytest
from hypothesis import given, strategies as st
from pydantic import ValidationError

from novel_flywheel.semantic_packets import (
    SemanticPacketContract,
    canonical_sha256,
    exact_ordered_partition,
    load_validated_packet,
    normalize_causal_packet_payload,
    packet_checkpoint_path,
    semantic_bisect,
    write_validated_packet,
)


AUTHORITY_SHA256 = "a" * 64


def causal_packet(**changes):
    value = {
        "core_goal": "Goal",
        "opening": {"pressure": "Opening pressure"},
        "cycles": [{
            "obstacle": "Obstacle", "effort": "Effort",
            "result": "Result", "state_change": "Changed",
        }],
        "accidents": [], "reversal": {}, "ending": "Ending",
        "question_chain": [], "relationship_arc": [],
        "covered_event_ids": ["EV-1", "EV-2"],
    }
    value.update(changes)
    return value


def packet_contract(*event_ids: str) -> SemanticPacketContract:
    return SemanticPacketContract(
        task_kind="short_causal_chain",
        authority_sha256=AUTHORITY_SHA256,
        owned_event_ids=event_ids,
    )


@given(
    size=st.integers(min_value=2, max_value=100),
    semantic_width=st.integers(min_value=1, max_value=12),
)
def test_semantic_bisect_is_exact_nonempty_and_prefers_natural_boundaries(
    size: int, semantic_width: int,
) -> None:
    units = tuple(f"EV-{index:08X}" for index in range(size))
    boundaries = tuple(index // semantic_width for index in range(size))

    left, right = semantic_bisect(units, boundary_keys=boundaries)

    assert exact_ordered_partition(units, (left, right))
    assert left and right
    natural_boundaries = [
        index for index in range(1, size)
        if boundaries[index - 1] != boundaries[index]
    ]
    if natural_boundaries:
        assert boundaries[len(left) - 1] != boundaries[len(left)]


def test_packet_contract_separates_read_only_context_from_owned_events() -> None:
    contract = SemanticPacketContract(
        task_kind="short_causal_chain",
        authority_sha256=AUTHORITY_SHA256,
        owned_event_ids=("ev-1", "EV-2"),
        context_event_ids=("ev-0", "ev-3"),
        segment_numbers=(1, 2),
    )

    assert contract.owned_event_ids == ("EV-1", "EV-2")
    assert contract.context_event_ids == ("EV-0", "EV-3")
    assert len(contract.packet_id) == 64

    with pytest.raises(ValidationError, match="context IDs"):
        SemanticPacketContract(
            task_kind="short_causal_chain",
            authority_sha256=AUTHORITY_SHA256,
            owned_event_ids=("EV-1",),
            context_event_ids=("EV-1",),
        )


def test_packet_contract_rejects_unknown_machine_control_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        SemanticPacketContract.model_validate({
            "task_kind": "short_causal_chain",
            "authority_sha256": AUTHORITY_SHA256,
            "owned_event_ids": ["EV-1"],
            "provider_should_skip_validation": True,
        })


@pytest.mark.parametrize("payload", [
    causal_packet(),
    causal_packet(cycles=[
        {
            "obstacle": "First obstacle", "effort": "First effort",
            "result": "First result", "state_change": "First change",
            "escalation": {"level": 2, "reason": "pressure"},
        },
        {
            "obstacle": "Second obstacle", "effort": "Second effort",
            "result": "Second result", "state_change": "Second change",
        },
    ]),
    causal_packet(
        core_goal={"surface": "查明真相", "inner": "接纳身份"},
        opening={"pressure": ["谣言", "证据"], "reader_question": "谁在说谎？"},
    ),
    causal_packet(
        question_chain="What changed and why?",
        relationship_arc={"before": "distrust", "after": "alliance"},
    ),
    causal_packet(
        story_weave={"threads": [{"name": "身份线", "status": "推进"}]},
        locale_note="跨类型描述元数据应被保留",
    ),
    causal_packet(
        provider_trace={"chunks": [{"index": 1}, {"index": 2}]},
        diagnostic_bundle=[{"dimension": "causality", "verdict": "pass"}],
    ),
], ids=[
    "canonical", "verbose-multi-cycle", "nested-global-fields",
    "mixed-scalar-containers", "unseen-story-weave-container",
    "unseen-provider-trace-wrapper",
])
def test_causal_packet_accepts_open_descriptive_topologies_with_stable_invariants(
    payload,
) -> None:
    normalized = normalize_causal_packet_payload(
        payload,
        expected_event_ids=("EV-1", "EV-2"),
        owns_opening=True,
        owns_ending=True,
    )

    assert normalized is not None
    assert normalized["covered_event_ids"] == ["EV-1", "EV-2"]
    assert all(
        all(cycle.get(key) for key in ("obstacle", "effort", "result", "state_change"))
        for cycle in normalized["cycles"]
    )


@pytest.mark.parametrize("payload", [
    causal_packet(cycles=[{
        "obstacle": "Obstacle", "effort": "Effort", "result": "Result",
    }]),
    causal_packet(covered_event_ids=["EV-2", "EV-1"]),
    causal_packet(provider_should_skip_validation=True),
    causal_packet(core_goal="Out-of-scope global", opening={"pressure": "wrong"}),
], ids=[
    "incomplete-cycle", "reordered-ownership",
    "unknown-machine-control", "out-of-scope-global-fields",
])
def test_causal_packet_rejects_incomplete_ambiguous_or_unsafe_variants(payload) -> None:
    normalized = normalize_causal_packet_payload(
        payload,
        expected_event_ids=("EV-1", "EV-2"),
        owns_opening=payload.get("core_goal") != "Out-of-scope global",
        owns_ending=True,
    )

    assert normalized is None


def test_validated_packet_checkpoint_is_content_addressed_and_tamper_safe(
    tmp_path,
) -> None:
    contract = packet_contract("EV-1")
    payload = {
        "core_goal": "Goal",
        "opening": {},
        "cycles": [{
            "obstacle": "Obstacle", "effort": "Effort",
            "result": "Result", "state_change": "Changed",
        }],
        "accidents": [], "reversal": {}, "ending": "Ending",
        "question_chain": [], "relationship_arc": [],
        "covered_event_ids": ["EV-1"],
    }

    path = write_validated_packet(tmp_path, contract, payload)

    assert path == packet_checkpoint_path(tmp_path, contract)
    assert load_validated_packet(tmp_path, contract) == payload

    checkpoint = json.loads(path.read_text(encoding="utf-8"))
    checkpoint["payload"]["covered_event_ids"] = ["EV-OTHER"]
    path.write_text(json.dumps(checkpoint), encoding="utf-8")
    assert load_validated_packet(tmp_path, contract) is None
    assert canonical_sha256(payload) != canonical_sha256(checkpoint["payload"])
