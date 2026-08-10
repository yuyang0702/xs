import json

import pytest

from novel_flywheel.generated_artifacts import (
    ArtifactConversionError,
    GeneratedArtifactGateway,
)
from novel_flywheel.semantic_packets import normalize_causal_packet_payload


GENRE_REALIZATIONS = (
    ("mystery", "cycles", "root"),
    ("romance", "beats_of_change", "root"),
    ("xianxia", "tribulation_motion", "nested"),
    ("science-fiction", "phase_delta", "double_nested"),
    ("historical", "motion_bundle_omega", "fenced"),
    ("slice-of-life", "ordinary_turns", "malformed"),
)


def _cycle(genre: str) -> dict:
    return {
        "obstacle": f"{genre} pressure",
        "effort": f"{genre} agency",
        "result": f"{genre} consequence",
        "state_change": f"{genre} state transition",
    }


def _normalizer(value):
    return normalize_causal_packet_payload(
        value, expected_event_ids=("EV-1",),
        owns_opening=True, owns_ending=True,
    )


@pytest.mark.parametrize("genre,container,topology", GENRE_REALIZATIONS)
def test_p5_cross_genre_open_world_topologies_share_one_contract(
    genre, container, topology,
) -> None:
    cycle = _cycle(genre)
    if topology == "root":
        payload = {container: [cycle], "covered_event_ids": ["EV-1"]}
    elif topology == "nested":
        payload = {"delivery": {container: [cycle]}, "ownership": ["EV-1"]}
    else:
        payload = {
            "provider": {"response": {container: [cycle]}},
            "authority_echo": {"ordered_ids": ["EV-1"]},
        }
    raw = json.dumps(payload, ensure_ascii=False)
    if topology == "fenced":
        raw = f"```json\n{raw}\n```"
    elif topology == "malformed":
        raw = raw[:-1] + ",}"

    result = GeneratedArtifactGateway().convert_object(
        raw, contract_name="short_causal_chain",
        semantic_normalizer=_normalizer,
        expected_event_ids=("EV-1",),
    )

    assert result.payload["cycles"] == [cycle]
    assert result.payload["covered_event_ids"] == ["EV-1"]
    assert result.audit.semantic_valid is True


def test_p5_unknown_semantic_vocabulary_requests_protocol_repair_instead_of_guessing() -> None:
    raw = json.dumps({
        "motion_bundle_psi": [{
            "barrier": "locked archive",
            "attempt": "enter through service passage",
            "outcome": "the ledger is recovered",
            "world_delta": "the suspect list narrows",
        }],
        "authority_echo": ["EV-1"],
    })

    with pytest.raises(ArtifactConversionError) as caught:
        GeneratedArtifactGateway().convert_object(
            raw, contract_name="short_causal_chain",
            semantic_normalizer=_normalizer,
            expected_event_ids=("EV-1",),
        )

    assert caught.value.audit.failure_code == "baml_alignment_failed"


@pytest.mark.parametrize("ownership", [
    ["EV-2", "EV-1"], ["EV-1", "EV-1"], ["EV-OTHER"],
])
def test_p5_reordered_duplicate_or_foreign_ownership_never_auto_converts(ownership) -> None:
    raw = json.dumps({
        "unseen_motion": [_cycle("thriller")], "authority_echo": ownership,
    })

    with pytest.raises(ArtifactConversionError) as caught:
        GeneratedArtifactGateway().convert_object(
            raw, contract_name="short_causal_chain",
            semantic_normalizer=_normalizer,
            expected_event_ids=("EV-1",),
        )

    assert caught.value.audit.failure_code == "event_ownership_mismatch"


def test_p5_unknown_nested_machine_control_never_crosses_authority_boundary() -> None:
    raw = json.dumps({
        "unseen_motion": [_cycle("fantasy")],
        "authority_echo": ["EV-1"],
        "provider_meta": {"override_validation": True},
    })

    with pytest.raises(ArtifactConversionError) as caught:
        GeneratedArtifactGateway().convert_object(
            raw, contract_name="short_causal_chain",
            semantic_normalizer=_normalizer,
            expected_event_ids=("EV-1",),
        )

    assert caught.value.audit.failure_code == "unknown_machine_control"
