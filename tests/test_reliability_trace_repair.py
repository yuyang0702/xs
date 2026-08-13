from __future__ import annotations

import hashlib

import pytest

from novel_flywheel.reliability_trace import changed_paths, repair_diff_view
from novel_flywheel.generated_artifacts import ReliabilityTraceEnvelopeV1
from novel_flywheel.story_state import validate_locked_facts


@pytest.mark.parametrize(
    ("name", "source", "mutated"),
    [
        ("actor_swap", "甲交出钥匙。锚点不变。", "乙交出钥匙。锚点不变。"),
        ("negation", "甲打开门。锚点不变。", "甲没有打开门。锚点不变。"),
        ("time_inversion", "先取证后审问。锚点不变。", "先审问后取证。锚点不变。"),
        ("knowledge_owner", "甲知道暗号。锚点不变。", "乙知道暗号。锚点不变。"),
        ("relationship_direction", "甲保护乙。锚点不变。", "乙保护甲。锚点不变。"),
    ],
)
def test_semantic_mutation_family_remains_characterized_not_fixed(
    name: str, source: str, mutated: str,
) -> None:
    state = {"locked_facts": [{"key": "anchor", "value": "锚点不变"}]}

    # This is the current validator's actual behavior: it protects the exact
    # locked phrase but does not review all surrounding semantic dimensions.
    assert validate_locked_facts(source, mutated, state) == []
    assert hashlib.sha256(source.encode()).hexdigest() != hashlib.sha256(mutated.encode()).hexdigest()
    assert name


def test_unauthorized_repair_diff_is_observed_without_enforcement() -> None:
    before = {
        "target": {"location": "上海"},
        "unrelated": {"knowledge_owner": "甲"},
    }
    after = {
        "target": {"location": "北京"},
        "unrelated": {"knowledge_owner": "乙"},
    }
    paths = changed_paths(before, after)
    assert paths == ["$.target.location", "$.unrelated.knowledge_owner"]

    event = ReliabilityTraceEnvelopeV1.model_validate({
        "schema": "ReliabilityTraceEnvelopeV1",
        "event_id": "repair-event-0000000001",
        "correlation_id": "repair-run",
        "sequence": 1,
        "event_type": "repair_diff",
        "source_component": "test",
        "source_writer": "minfix",
        "semantic_domain": "occurred_current",
        "observation_status": "confirmed",
        "object_old_hash": "a" * 64,
        "object_new_hash": "b" * 64,
        "payload": {
            "allowed_scope_source": "$.target",
            "changed_paths": paths,
            "validators_rerun": ["target_validator"],
            "unauthorized_change": True,
        },
    })
    view = repair_diff_view([event])
    assert view[0]["unauthorized_change"] is True
    assert "unrelated" in view[0]["changed_paths"][1]
