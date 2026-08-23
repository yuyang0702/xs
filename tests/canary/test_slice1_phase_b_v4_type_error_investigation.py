from __future__ import annotations

from dataclasses import asdict, is_dataclass
import hashlib
import inspect
import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from novel_flywheel.db import Database
from novel_flywheel.domain.models import ModelResponse, ProviderOutputShapeV1
from novel_flywheel.generated_artifacts import ArtifactConversionAudit
from novel_flywheel.models import ModelGateway
from novel_flywheel.planning_v2_slice1 import (
    EventRealizationCandidateV1,
    EventRealizationInputAuthorityV1,
    build_event_realization_artifact,
    convert_event_realization_candidate,
    freeze_validated_artifact,
    normalize_event_realization_input_authority_v1,
    validate_event_realization_artifact,
)
from novel_flywheel.providers.registry import ResolvedModel
from novel_flywheel.structured_artifacts import (
    StructuredArtifactContract,
    StructuredOutputRequirement,
)
import tools.canary.slice1_phase_b_current_skill as base
import tools.canary.slice1_phase_b_v4_single_dispatch as launcher


ROOT = Path(__file__).resolve().parents[2]
REAL_ERROR_MESSAGE_SHA256 = (
    "b0765aa80a001070478e477edd5f18f37a7d61d14a1fe38eb42783da0d2cde38"
)


class _StaticReasoningAndTextAdapter:
    def __init__(self, response: ModelResponse) -> None:
        self.response = response
        self.calls = 0

    async def complete(self, _request):
        self.calls += 1
        return self.response


class _StaticRegistry:
    def __init__(self, adapter: _StaticReasoningAndTextAdapter) -> None:
        self.adapter = adapter

    def resolve(self, provider_id: str, model_id: str) -> ResolvedModel:
        return ResolvedModel(
            provider_id,
            model_id,
            model_id,
            self.adapter,
            {"structured_output": "strict_json_schema"},
            "7" * 64,
        )


@pytest.mark.asyncio
async def test_v4_valid_reasoning_and_visible_final_reproduces_sealed_type_error(
    tmp_path: Path,
) -> None:
    synthetic_final = json.dumps(
        {
            "title": "Synthetic crossing",
            "narrative": (
                "The synthetic actor makes a clear choice, meets resistance, "
                "and preserves the required consequence for the next event."
            ),
        }
    )
    shape = ProviderOutputShapeV1(
        provider_family="deterministic_fake",
        protocol="offline",
        finish_reason="end_turn",
        output_tokens=120,
        content_block_count=2,
        content_block_type_sequence=("thinking", "text"),
        text_block_count=1,
        provider_visible_text_chars=len(synthetic_final),
        tool_call_count=0,
        reasoning_block_count=1,
        unknown_block_count=0,
        transport_complete=True,
        normalized_visible_text_chars=len(synthetic_final),
        normalized_tool_call_count=0,
        adapter_projection_status="exact",
        shape_sha256="8" * 64,
    )
    response = ModelResponse(
        text=synthetic_final,
        finish_reason="end_turn",
        output_tokens=120,
        provider_state={
            "content": (
                {"type": "thinking", "thinking": "synthetic reasoning"},
                {"type": "text", "text": synthetic_final},
            ),
            "transport_complete": True,
        },
        output_shape=shape,
    )
    adapter = _StaticReasoningAndTextAdapter(response)
    database = Database(tmp_path / "app.db")
    database.migrate()
    database.save_role_binding("planning", "primary", "model", None, None)
    gateway = ModelGateway(database, _StaticRegistry(adapter))
    contract = StructuredArtifactContract(
        name="planning_event_realization_shadow_v1",
        version=1,
        schema=EventRealizationCandidateV1.model_json_schema(),
        runtime_authority={"synthetic_topology_only": True},
    )

    result = await gateway.complete_route(
        "primary",
        "planning",
        "synthetic system",
        "synthetic user",
        max_output_tokens=4624,
        contract=contract,
        structured_requirement=StructuredOutputRequirement.PLAIN_TEXT,
    )
    assert adapter.calls == 1
    assert result.text == synthetic_final
    assert response.output_shape is not None
    assert response.output_shape.reasoning_block_count == 1
    assert response.output_shape.provider_visible_text_chars > 0

    _, authority_value = base.load_fixture_binding(ROOT)
    authority = EventRealizationInputAuthorityV1.model_validate(
        normalize_event_realization_input_authority_v1(authority_value)
    )
    candidate, conversion = convert_event_realization_candidate(
        result.text, authority=authority
    )
    artifact = build_event_realization_artifact(
        authority, candidate, producer_kind="future_model_shadow"
    )
    validation = validate_event_realization_artifact(artifact, authority)
    assert validation.status == "PASS"
    frozen = freeze_validated_artifact(artifact, validation)
    assert frozen.freeze_state == "FROZEN"

    assert type(conversion) is ArtifactConversionAudit
    assert isinstance(conversion, BaseModel)
    assert is_dataclass(conversion) is False
    with pytest.raises(TypeError) as caught:
        asdict(conversion)

    message = str(caught.value)
    assert message == "asdict() should be called on dataclass instances"
    assert hashlib.sha256(message.encode("utf-8")).hexdigest() == (
        REAL_ERROR_MESSAGE_SHA256
    )
    source, first_line = inspect.getsourcelines(launcher.execute_authorized_once)
    call_line = next(
        first_line + offset
        for offset, text in enumerate(source)
        if "asdict(conversion)" in text
    )
    assert call_line == 896
