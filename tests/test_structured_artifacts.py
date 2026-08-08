import pytest
from pydantic import ValidationError

from novel_flywheel.structured_artifacts import (
    StructuredArtifactContract,
    StructuredOutputCapability,
    StructuredOutputRequirement,
    capability_satisfies,
    configured_structured_output_capability,
)


@pytest.mark.parametrize("capabilities", [
    {},
    {"structured_output": "auto", "model_name": "gpt-5"},
    {"structured_output": "unknown", "provider_name": "Claude relay"},
])
def test_third_party_brand_never_implies_structured_capability(capabilities) -> None:
    assert configured_structured_output_capability(
        capabilities,
    ) == StructuredOutputCapability.PLAIN_TEXT


@pytest.mark.parametrize(("configured", "expected"), [
    ("json_object", StructuredOutputCapability.JSON_OBJECT),
    ("strict_json_schema", StructuredOutputCapability.STRICT_JSON_SCHEMA),
    ("strict_tool", StructuredOutputCapability.STRICT_TOOL),
])
def test_explicit_route_capability_is_preserved(configured, expected) -> None:
    assert configured_structured_output_capability({
        "structured_output": configured,
    }) == expected


def test_strict_requirement_never_degrades_to_json_object() -> None:
    assert not capability_satisfies(
        StructuredOutputCapability.JSON_OBJECT,
        StructuredOutputRequirement.STRICT,
    )
    assert capability_satisfies(
        StructuredOutputCapability.STRICT_JSON_SCHEMA,
        StructuredOutputRequirement.STRICT,
    )
    assert capability_satisfies(
        StructuredOutputCapability.STRICT_TOOL,
        StructuredOutputRequirement.STRICT,
    )


def test_structured_artifact_contract_is_closed_and_versioned() -> None:
    contract = StructuredArtifactContract(
        name="planning_packet",
        schema={
            "type": "object",
            "properties": {"events": {"type": "array"}},
            "required": ["events"],
            "additionalProperties": False,
        },
        runtime_authority={"segment": 5, "event_ids": ["EV-BEAE4985"]},
    )

    assert contract.provider_schema()["strict"] is True
    assert contract.version == 1
    with pytest.raises(ValidationError):
        StructuredArtifactContract(
            name="planning_packet",
            schema={"type": "object"},
            unexpected_control="unsafe",
        )
