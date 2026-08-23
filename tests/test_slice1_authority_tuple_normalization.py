from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from novel_flywheel.planning_v2_slice1 import (
    EventRealizationInputAuthorityV1,
    normalize_event_realization_input_authority_v1,
)
import tools.canary.slice1_phase_b_current_skill as phase_b


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (("a", "b"), ("a", "b")),
        (["a", "b"], ("a", "b")),
        ([], ()),
        (["a", "a", "b"], ("a", "a", "b")),
        (["b", "a"], ("b", "a")),
    ],
)
def test_exact_tuple_normalization_preserves_sequence(source, expected) -> None:
    value = {
        "formal_event_ids": source,
        "segment_event_ids": [source],
        "dependency_artifact_ids": source,
        "required_obligation_ids": source,
    }
    normalized = normalize_event_realization_input_authority_v1(value)
    assert normalized["formal_event_ids"] == expected
    assert normalized["segment_event_ids"] == (expected,)
    assert normalized["dependency_artifact_ids"] == expected
    assert normalized["required_obligation_ids"] == expected
    assert all(isinstance(normalized[name], tuple) for name in (
        "formal_event_ids", "segment_event_ids", "dependency_artifact_ids",
        "required_obligation_ids",
    ))


@pytest.mark.parametrize("bad", ["event-1", {"a", "b"}, {"a": 1}, None])
def test_unsupported_authority_containers_fail_closed(bad) -> None:
    with pytest.raises(TypeError):
        normalize_event_realization_input_authority_v1({
            "formal_event_ids": bad,
            "segment_event_ids": [],
            "dependency_artifact_ids": [],
            "required_obligation_ids": [],
        })


def test_generator_is_rejected_without_consumption() -> None:
    touched = False

    def values() -> Generator[str, None, None]:
        nonlocal touched
        touched = True
        yield "a"

    source = values()
    with pytest.raises(TypeError):
        normalize_event_realization_input_authority_v1({
            "formal_event_ids": source,
            "segment_event_ids": [],
            "dependency_artifact_ids": [],
            "required_obligation_ids": [],
        })
    assert touched is False


def test_phase_b_rehydrated_authority_validates_as_exact_tuples() -> None:
    _, authority = phase_b.load_fixture_binding(Path.cwd())
    assert all(isinstance(authority[name], tuple) for name in (
        "formal_event_ids", "segment_event_ids", "dependency_artifact_ids",
        "required_obligation_ids",
    ))
    validated = EventRealizationInputAuthorityV1.model_validate(
        normalize_event_realization_input_authority_v1(authority),
    )
    assert validated.formal_event_ids == authority["formal_event_ids"]
    assert validated.segment_event_ids == authority["segment_event_ids"]


def test_bad_element_still_fails_pydantic_validation() -> None:
    _, authority = phase_b.load_fixture_binding(Path.cwd())
    authority["dependency_artifact_ids"] = [1]
    with pytest.raises(Exception):
        EventRealizationInputAuthorityV1.model_validate(
            normalize_event_realization_input_authority_v1(authority),
        )
