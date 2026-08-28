from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from novel_flywheel.hybrid_skill_context import (
    ACTIONABILITY_CLASSES,
    DEFAULT_HYBRID_SKILL_CONTEXT_SHADOW_ENABLED,
    DEPENDENCY_TYPES,
    HYBRID_ARCHITECTURE_DECISION,
    HYBRID_CONTEXT_VERSION,
    OVERLAP_CLASSES,
    HybridCapacityError,
    HybridDependencyEdgeV1,
    HybridDependencyError,
    HybridProtectedBudgetV1,
    HybridShadowInputV1,
    HybridSkillContextCompilerV1,
    HybridSkillContextShadowObserverV1,
    HybridSkillSectionIndexV2,
    extract_demand_features_v1,
)
from novel_flywheel.models import ModelResult
from novel_flywheel.runtime_skill_profiles import (
    SkillLoadDecisionInputsV1,
    build_planning_v2_event_realization_profile_demand_aware,
    render_skill_context,
)
from test_phase05_evidence_closure import _service


ROOT = Path(__file__).resolve().parents[1]
INDEX_V1 = ROOT / "vendor/novel-skills/skill-section-index-v1.json"
INDEX_V2 = ROOT / "vendor/novel-skills/skill-section-index-v2.json"
DESIGN_ROOT = ROOT / "docs/superpowers/reports/skill-v3-hybrid-skill-context-architecture-design-v1"


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _index() -> HybridSkillSectionIndexV2:
    return HybridSkillSectionIndexV2.load(INDEX_V2, INDEX_V1, ROOT)


def _decision_inputs() -> SkillLoadDecisionInputsV1:
    return SkillLoadDecisionInputsV1.model_validate({
        "authority_revision": 1,
        "authority_hash": "a" * 64,
        "actor_refs_status": "present",
        "world_refs_status": "present",
        "actor_ref_count": 1,
        "world_ref_count": 1,
        "actor_refs": ("actor-fixture",),
        "location_refs": ("location-fixture",),
    })


def _baseline(demand: str = "character-heavy") -> str:
    profile = build_planning_v2_event_realization_profile_demand_aware(
        ROOT / "vendor/novel-skills/source",
        _decision_inputs(),
        pair_creative_demand_class=demand,
    )
    text, receipt = render_skill_context(
        profile.advisory_rules,
        profile.mandatory_rules,
        profile.context_budget_policy,
        profile_hash=profile.canonical_profile_sha256,
    )
    assert receipt.status == "NONE"
    assert not receipt.excluded_rule_ids
    return text


def _request(
    index: HybridSkillSectionIndexV2,
    demand: str = "character-heavy",
    **changes,
) -> HybridShadowInputV1:
    baseline = _baseline(demand)
    reference = "REFERENCE-DERIVED GUIDANCE\nNON-SKILL ADVISORY\n"
    base = HybridShadowInputV1(
        stage="planning",
        substage="event_realization",
        task_case=f"offline-{demand}",
        task_contract_id="planning_semantic_v2@2",
        task_contract_schema_sha256="1" * 64,
        creative_demand_class=demand,
        demand_signals={
            "actor_refs_present": demand in {"character-heavy", "mixed"},
            "relationship_pressure_present": demand == "character-heavy",
            "causal_chain_present": True,
            "dialogue_required": demand == "character-heavy",
            "opposition_present": demand == "conflict-pacing-heavy",
            "world_refs_present": demand in {"world-heavy", "mixed"},
            "setup_payoff_present": demand in {"setup-payoff-heavy", "mixed"},
            "anti_template_required": demand in {"character-heavy", "mixed"},
        },
        resolved_skill_ids=index.source_index.skill_ids,
        resolved_skill_source_hashes=tuple(
            (skill, index.source_index.skill_source_sha256[skill])
            for skill in index.source_index.skill_ids
        ),
        authority_fact_hashes=(("authority", "2" * 64),),
        production_baseline_context=baseline,
        baseline_source_receipt={"source": "production-runtime-boundary"},
        baseline_compactor_receipt={"compactor": "exact"},
        protected_non_skill_prefix=reference + "\nSkill instructions (advisory):\n",
        reference_guidance_context=reference,
        production_model_input_sha256="3" * 64,
        budget=HybridProtectedBudgetV1(
            safe_context_window_tokens=32768,
            output_reserve_tokens=4624,
            mandatory_authority_tokens=600,
            reference_guidance_tokens=120,
            baseline_skill_foundation_tokens=800,
            output_contract_tokens=240,
            wrapper_and_estimator_margin_tokens=1024,
        ),
        expected_baseline_context_sha256=_sha(baseline),
        expected_reference_guidance_sha256=_sha(reference),
    )
    return replace(base, **changes)


def _replace_index(
    index: HybridSkillSectionIndexV2,
    *,
    policies=None,
    edges=None,
) -> HybridSkillSectionIndexV2:
    return HybridSkillSectionIndexV2(
        source_index=index.source_index,
        definition_sha256=index.definition_sha256,
        design_manifest_definition_sha256=index.design_manifest_definition_sha256,
        root_cause_manifest_definition_sha256=index.root_cause_manifest_definition_sha256,
        section_policies=policies or index.section_policies,
        packets=index.packets,
        dependency_edges=tuple(edges or index.dependency_edges),
        demand_class_features=index.demand_class_features,
        demand_packet_order=index.demand_packet_order,
        signal_feature_map=index.signal_feature_map,
    )


def test_hybrid_shadow_contract_and_index_bind_sealed_design() -> None:
    index = _index()
    design = json.loads((DESIGN_ROOT / "architecture-decision-v1.json").read_text(encoding="utf-8"))
    assert HYBRID_CONTEXT_VERSION == "hybrid-skill-context-shadow-v1"
    assert DEFAULT_HYBRID_SKILL_CONTEXT_SHADOW_ENABLED is False
    assert index.definition_sha256 == "bce8d4ba48b17f050f935238fa9b4be14fe2abfb1aef88ede2222da91eaa0e68"
    assert design["hybrid_architecture_decision"] == HYBRID_ARCHITECTURE_DECISION
    assert index.design_manifest_definition_sha256 == "e490accef7716d20d60060fe2e7f82fde0e8374f22c19cfc19b97224df3e1505"
    assert index.root_cause_manifest_definition_sha256 == "7022b932ad873dfb6a6d20dbd95538dff59d2f1acb0ba2cd417d03240d3df4ed"
    assert set(item.actionability_class for item in index.section_policies.values()) == ACTIONABILITY_CLASSES
    assert set(item.overlap_classification for item in index.section_policies.values()) <= OVERLAP_CLASSES
    assert set(item.dependency_type for item in index.dependency_edges) == DEPENDENCY_TYPES


def test_exact_production_baseline_foundation_is_preserved_as_prefix() -> None:
    index = _index()
    request = _request(index)
    baseline = request.production_baseline_context
    assert _sha(baseline) == "7d0f6309ede2261f2f6a1098d394937948bf5b50eb9248266ab350fd91da9adc"
    assert len(baseline) == 2925
    result = HybridSkillContextCompilerV1(index).materialize(request)
    assert result.baseline_context == baseline
    assert result.final_hybrid_advisory.startswith(
        request.protected_non_skill_prefix + baseline
    )
    assert result.receipt["BASELINE_CONTEXT_SHA"] == _sha(baseline)
    assert result.receipt["TRUNCATION_OCCURRED"] == "NO"
    assert result.receipt["SHEDDING_OCCURRED"] == "NO"


@pytest.mark.parametrize(
    "demand",
    ("character-heavy", "world-heavy", "conflict-pacing-heavy", "setup-payoff-heavy", "mixed"),
)
def test_demand_extraction_packets_and_receipts_are_deterministic(demand: str) -> None:
    index = _index()
    request = _request(index, demand)
    features_a = extract_demand_features_v1(demand, request.demand_signals, index)
    features_b = extract_demand_features_v1(demand, dict(reversed(tuple(request.demand_signals.items()))), index)
    assert features_a == features_b
    compiler = HybridSkillContextCompilerV1(index)
    first = compiler.materialize(request)
    second = compiler.materialize(request)
    assert first.receipt == second.receipt
    assert first.final_hybrid_advisory == second.final_hybrid_advisory
    assert first.receipt["SUPPLEMENT_PACKET_IDS"] == list(index.demand_packet_order[demand])
    assert first.receipt["SHADOW_RESULT"] == "PASS"
    assert first.receipt["VERBATIM_MISMATCH"] == 0
    assert first.receipt["WRONG_LAYER_SECTION_COUNT"] == 0


def test_character_packet_closes_known_semantic_and_boundary_gaps() -> None:
    index = _index()
    result = HybridSkillContextCompilerV1(index).materialize(_request(index))
    selected = set(result.receipt["SUPPLEMENT_SECTION_IDS"])
    expected = {
        "sv3-4c39329c602fd48e", "sv3-10e4ba0c5b7509b4",
        "sv3-b75227453c1cc26a", "sv3-8e321726b4ebdcec",
        "sv3-faecc1466817d8aa", "sv3-13580b3cdbef263e",
        "sv3-2985467b5f2bf929", "sv3-5f738df332e0919f",
        "sv3-60d4bee497e4c0dc", "sv3-ac7aa3aed8a7d237",
        "sv3-2ced894267dc51e3", "sv3-972a75cb8ca8f0bd",
        "sv3-82ca2fdf9c28183b", "sv3-6e4a0b2625a01274",
        "sv3-ad3871e96cc16876",
    }
    assert selected == expected
    closure = result.receipt["SEMANTIC_DEPENDENCY_CLOSURE_RECEIPT"]
    assert closure["silent_dependency_drop_count"] == 0
    assert {edge["DEPENDENCY_TYPE"] for edge in closure["edges"]} == DEPENDENCY_TYPES
    assert result.receipt["ACTIONABILITY_DISTRIBUTION"]["LOW_ACTIONABILITY"] == 2
    assert result.receipt["ACTIONABILITY_DISTRIBUTION"]["HIGH_ACTIONABILITY"] > 2

    for packet_receipt in result.receipt["SUPPLEMENT_PACKET_RECEIPTS"]:
        packet_id = packet_receipt["PACKET_ID"]
        roots = set(index.packets[packet_id].root_section_ids)
        packet_sections = set(packet_receipt["ORDERED_SECTION_IDS"])
        packet_dependencies = set(packet_receipt["DEPENDENCY_SECTION_IDS"])
        assert roots <= packet_sections
        assert packet_dependencies == packet_sections - roots
        assert packet_sections <= selected


def test_verbatim_fidelity_and_exact_ownership_exception() -> None:
    index = _index()
    result = HybridSkillContextCompilerV1(index).materialize(_request(index))
    for section in result.ordered_sections:
        assert _sha(section.source_text) == section.section_content_sha256
        assert section.source_text in result.supplement_text
    voice = index.section_policies["sv3-b75227453c1cc26a"]
    assert voice.stage_ownership_exception == "PLANNING_CREATIVE_SUPPLEMENT_EXACT_SUBRANGE_V1"
    policies = dict(index.section_policies)
    policies[voice.section_id] = replace(voice, stage_ownership_exception=None)
    broken = _replace_index(index, policies=policies)
    projection = HybridSkillContextShadowObserverV1(
        HybridSkillContextCompilerV1(broken)
    )(_request(broken))
    assert projection["FAILURE_CODE"] == "OWNERSHIP_VIOLATION"
    assert projection["PRODUCTION_MODEL_INPUT_UNCHANGED"] == "YES"


def test_dependency_missing_and_undeclared_cycle_fail_observably() -> None:
    index = _index()
    missing = HybridDependencyEdgeV1(
        from_section_id="sv3-10e4ba0c5b7509b4",
        to_section_id="missing-section",
        dependency_type="FORMAL_DEPENDENCY",
        source_of_truth="test-injection",
        reason="negative injection",
    )
    missing_index = _replace_index(index, edges=(*index.dependency_edges, missing))
    with pytest.raises(HybridDependencyError, match="MISSING_DEPENDENCY_TARGET"):
        HybridSkillContextCompilerV1(missing_index).materialize(_request(missing_index))

    cycle = HybridDependencyEdgeV1(
        from_section_id="sv3-4c39329c602fd48e",
        to_section_id="sv3-10e4ba0c5b7509b4",
        dependency_type="FORMAL_DEPENDENCY",
        source_of_truth="test-injection",
        reason="undeclared cycle",
    )
    cycle_index = _replace_index(index, edges=(*index.dependency_edges, cycle))
    projection = HybridSkillContextShadowObserverV1(
        HybridSkillContextCompilerV1(cycle_index)
    )(_request(cycle_index))
    assert projection["FAILURE_CODE"] == "DEPENDENCY_CYCLE"
    assert projection["FAILURE_OBSERVABLE"] == "YES"


def test_contradiction_and_capacity_fail_closed_without_shrinkage() -> None:
    index = _index()
    policy = index.section_policies["sv3-10e4ba0c5b7509b4"]
    policies = dict(index.section_policies)
    policies[policy.section_id] = replace(
        policy, overlap_classification="CONTRADICTORY_RESTATEMENT",
    )
    contradictory = _replace_index(index, policies=policies)
    projection = HybridSkillContextShadowObserverV1(
        HybridSkillContextCompilerV1(contradictory)
    )(_request(contradictory))
    assert projection["FAILURE_CODE"] == "UNRESOLVED_CONTRADICTION"

    no_room = HybridProtectedBudgetV1(
        safe_context_window_tokens=4096,
        output_reserve_tokens=2000,
        mandatory_authority_tokens=500,
        reference_guidance_tokens=200,
        baseline_skill_foundation_tokens=700,
        output_contract_tokens=200,
        wrapper_and_estimator_margin_tokens=512,
    )
    with pytest.raises(HybridCapacityError) as caught:
        HybridSkillContextCompilerV1(index).materialize(
            _request(index, budget=no_room)
        )
    assert caught.value.code == "HYBRID_SUPPLEMENT_CAPACITY_NO_GO"
    assert caught.value.available_tokens == 0


@pytest.mark.parametrize(
    ("change", "failure"),
    (
        ({"expected_baseline_context_sha256": "0" * 64}, "BASELINE_IDENTITY_MISMATCH"),
        ({"expected_reference_guidance_sha256": "0" * 64}, "REFERENCE_GUIDANCE_IDENTITY_MISMATCH"),
    ),
)
def test_baseline_and_reference_identity_mismatch_are_typed(change, failure) -> None:
    index = _index()
    request = _request(index, **change)
    projection = HybridSkillContextShadowObserverV1(
        HybridSkillContextCompilerV1(index)
    )(request)
    assert projection["FAILURE_CODE"] == failure
    assert projection["RAW_PROMPT_PERSISTED"] == "NO"
    assert projection["NO_EXTERNAL_CALL"] == "YES"


def test_receipt_serialization_and_unexpected_exception_are_bounded() -> None:
    index = _index()

    def broken_serializer(_value):
        raise TypeError("PRIVATE receipt serialization text")

    serialization = HybridSkillContextShadowObserverV1(
        HybridSkillContextCompilerV1(index), serializer=broken_serializer,
    )(_request(index))
    assert serialization["FAILURE_CODE"] == "RECEIPT_SERIALIZATION_FAILURE"
    assert "PRIVATE" not in json.dumps(serialization)

    class BrokenCompiler:
        def materialize(self, _request):
            raise RuntimeError("PRIVATE unexpected compiler text")

    unexpected = HybridSkillContextShadowObserverV1(BrokenCompiler())(_request(index))
    assert unexpected["FAILURE_CODE"] == "UNEXPECTED_COMPILER_EXCEPTION"
    assert "PRIVATE" not in json.dumps(unexpected)


def test_process_level_interrupt_is_not_swallowed_by_shadow_observer() -> None:
    index = _index()

    class InterruptedCompiler:
        def materialize(self, _request):
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        HybridSkillContextShadowObserverV1(InterruptedCompiler())(
            _request(index)
        )


class _Gateway:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    async def complete(self, role, system, user, max_output_tokens=None):
        self.calls.append((role, system, user, max_output_tokens))
        return ModelResult("{}", {"role": role, "model_name": "offline"})


async def _run_planning(service, store, project, workflow: str) -> None:
    constraints = store.load_constraints(project.id)
    run_id, run_path = service._begin_run(project, "short-story", workflow)
    await service._stage(
        run_id, run_path, project, "planning", constraints, "same task",
        allow_tools=False,
    )


@pytest.mark.asyncio
async def test_disabled_and_enabled_shadow_never_change_production_model_input(tmp_path: Path) -> None:
    gateway = _Gateway()
    _db, store, project, service = _service(
        tmp_path, mode="short", gateway=gateway, title="Hybrid shadow identity",
    )
    project.metadata["creative_demand_class"] = "character-heavy"
    seen: list[HybridShadowInputV1] = []

    def observer(request: HybridShadowInputV1):
        seen.append(request)
        return {
            "SHADOW_RESULT": "PASS",
            "RECEIPT_SHA256": "4" * 64,
            "BASELINE_CONTEXT_SHA": _sha(request.production_baseline_context),
            "REFERENCE_GUIDANCE_SHA": _sha(request.reference_guidance_context),
            "SUPPLEMENT_RENDER_SHA": "5" * 64,
            "FINAL_HYBRID_ADVISORY_SHA": "6" * 64,
        }

    service.hybrid_skill_context_shadow_observer = observer
    await _run_planning(service, store, project, "hybrid-default-disabled")
    assert not seen
    service.hybrid_skill_context_shadow_enabled = True
    await _run_planning(service, store, project, "hybrid-enabled-shadow")
    assert len(seen) == 1
    assert gateway.calls[0] == gateway.calls[1]
    assert service.hybrid_skill_context_shadow_records[0]["HYBRID_MODEL_VISIBLE"] == "NO"
    assert service.hybrid_skill_context_shadow_records[0]["RAW_CONTENT_RETAINED"] == "NO"


@pytest.mark.asyncio
async def test_workflow_observer_exception_is_observable_and_production_fail_open(tmp_path: Path) -> None:
    gateway = _Gateway()
    _db, store, project, service = _service(
        tmp_path, mode="short", gateway=gateway, title="Hybrid shadow failure",
    )
    project.metadata["creative_demand_class"] = "character-heavy"
    await _run_planning(service, store, project, "hybrid-baseline")
    service.hybrid_skill_context_shadow_enabled = True
    service.hybrid_skill_context_shadow_observer = lambda _request: (_ for _ in ()).throw(
        RuntimeError("PRIVATE observer exception")
    )
    await _run_planning(service, store, project, "hybrid-fail-open")
    assert gateway.calls[0] == gateway.calls[1]
    assert service.hybrid_skill_context_shadow_failure_count == 1
    record = service.hybrid_skill_context_shadow_records[0]
    assert record["FAILURE_OBSERVABLE"] == "YES"
    assert record["PRODUCTION_MODEL_INPUT_UNCHANGED"] == "YES"
    assert "PRIVATE" not in json.dumps(record)


def test_workflow_shadow_request_construction_failure_is_observable(tmp_path: Path) -> None:
    gateway = _Gateway()
    _db, _store, _project, service = _service(
        tmp_path, mode="short", gateway=gateway, title="Hybrid request failure",
    )
    service.hybrid_skill_context_shadow_enabled = True
    service.hybrid_skill_context_shadow_observer = lambda _request: pytest.fail(
        "observer must not run after request construction fails"
    )

    def broken_request_factory() -> HybridShadowInputV1:
        raise RuntimeError("PRIVATE request construction exception")

    service._observe_hybrid_skill_context_shadow(
        "7" * 64, broken_request_factory
    )

    assert service.hybrid_skill_context_shadow_failure_count == 1
    record = service.hybrid_skill_context_shadow_records[0]
    assert record["FAILURE_CODE"] == "UNEXPECTED_REQUEST_CONSTRUCTION_EXCEPTION"
    assert record["PRODUCTION_MODEL_INPUT_SHA"] == "7" * 64
    assert record["PRODUCTION_MODEL_INPUT_UNCHANGED"] == "YES"
    assert "PRIVATE" not in json.dumps(record)
