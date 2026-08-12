import ast
import json
from pathlib import Path

import pytest

from novel_flywheel.generated_artifacts import (
    ARTIFACT_CONTRACT_REGISTRY,
    CONTRACT_ADAPTER_REGISTRY,
    EXECUTABLE_RECOVERY_STEP_OWNERS,
    ArtifactContractRegistration,
    ArtifactConversionError,
    GeneratedArtifactGateway,
    adapt_registered_contract,
    write_conversion_audit,
    _baml_causal_cycles,
    validate_executable_contract_registry,
)
from novel_flywheel.semantic_packets import normalize_causal_packet_payload


def _cycle(**changes):
    value = {
        "obstacle": "门被封锁", "effort": "寻找侧门",
        "result": "进入档案室", "state_change": "取得新线索",
    }
    value.update(changes)
    return value


def _normalizer(*, owns_opening=True, owns_ending=True):
    return lambda value: normalize_causal_packet_payload(
        value, expected_event_ids=("EV-1",),
        owns_opening=owns_opening, owns_ending=owns_ending,
    )


def test_generated_baml_parser_contract_aligns_cycle_elements() -> None:
    assert _baml_causal_cycles([_cycle()]) == [_cycle()]


def test_p0_registry_covers_planning_writing_quality_and_runtime_recovery() -> None:
    assert {item.phase for item in ARTIFACT_CONTRACT_REGISTRY.values()} >= {
        "planning", "writing", "quality",
    }
    assert ARTIFACT_CONTRACT_REGISTRY["short_causal_chain"].parser_strategy == "baml_sap"
    assert ARTIFACT_CONTRACT_REGISTRY["reference_distillation_region"].version == 2
    assert "attribution" in (
        ARTIFACT_CONTRACT_REGISTRY["reference_distillation_region"].semantic_authority
    )
    assert "MaterialAuditReceiptV1" in (
        ARTIFACT_CONTRACT_REGISTRY["material_audit"].semantic_authority
    )
    assert "MaterialImpactOutput" in (
        ARTIFACT_CONTRACT_REGISTRY[
            "material_impact_analysis"
        ].semantic_authority
    )
    assert "exact-substring" in (
        ARTIFACT_CONTRACT_REGISTRY[
            "outline_material_manifest"
        ].semantic_authority
    )
    assert "change-ID" in (
        ARTIFACT_CONTRACT_REGISTRY[
            "outline_semantic_review"
        ].semantic_authority
    )
    assert {
        "draft_atomic_semantic_receipt",
        "draft_segment_semantic_receipt",
        "draft_whole_semantic_receipt",
        "draft_whole_window_receipt",
        "draft_whole_reducer_receipt",
    } <= set(ARTIFACT_CONTRACT_REGISTRY)
    assert "beat" in (
        ARTIFACT_CONTRACT_REGISTRY[
            "draft_atomic_semantic_receipt"
        ].semantic_authority
    )
    assert "whole-story" in (
        ARTIFACT_CONTRACT_REGISTRY[
            "draft_whole_semantic_receipt"
        ].semantic_authority
    )
    assert {
        "revision_plan",
        "revision_patch_contract",
        "final_review",
        "final_review_window",
        "final_review_regional",
        "final_review_detail",
        "reader_review",
        "short_maintenance_facts",
        "long_setup_maintenance",
        "long_chapter_maintenance",
    } <= set(ARTIFACT_CONTRACT_REGISTRY)
    assert "minimal_regeneration" in ARTIFACT_CONTRACT_REGISTRY["final_review"].recovery_ladder
    assert all(item.semantic_authority for item in ARTIFACT_CONTRACT_REGISTRY.values())
    assert all(item.descriptive_fields == "open" for item in ARTIFACT_CONTRACT_REGISTRY.values())
    assert all(item.machine_control_fields == "closed" for item in ARTIFACT_CONTRACT_REGISTRY.values())
    assert all(
        item.narrative_invariants == "runtime_authoritative"
        for item in ARTIFACT_CONTRACT_REGISTRY.values()
    )


def test_p0_every_declared_recovery_step_has_one_executable_owner() -> None:
    validate_executable_contract_registry()
    declared = {
        step
        for registration in ARTIFACT_CONTRACT_REGISTRY.values()
        for step in registration.recovery_ladder
    }

    assert declared <= set(EXECUTABLE_RECOVERY_STEP_OWNERS)
    assert all(EXECUTABLE_RECOVERY_STEP_OWNERS[step] for step in declared)


def test_p0_contract_registry_rejects_an_invalid_recovery_order(monkeypatch) -> None:
    monkeypatch.setitem(
        ARTIFACT_CONTRACT_REGISTRY,
        "test_invalid_order",
        ArtifactContractRegistration(
            name="test_invalid_order",
            phase="runtime",
            semantic_authority="test-only authority",
            recovery_ladder=(
                "exact_json", "model_fallback", "semantic_protocol_retry",
            ),
        ),
    )

    with pytest.raises(RuntimeError, match="recovery_order_invalid"):
        validate_executable_contract_registry()


def test_contract_adapters_are_versioned_provider_and_narrative_agnostic() -> None:
    adapters = [
        item for registrations in CONTRACT_ADAPTER_REGISTRY.values()
        for item in registrations
    ]

    assert adapters
    assert all(item.version >= 1 for item in adapters)
    assert all(item.provider_agnostic for item in adapters)
    assert all(item.narrative_agnostic for item in adapters)
    serialized = json.dumps(
        [item.model_dump(mode="json") for item in adapters],
        ensure_ascii=False,
    ).casefold()
    assert not any(name in serialized for name in (
        "deepseek", "openai", "claude", "gemini", "romance", "suspense",
    ))


def test_contract_adapter_architecture_budget_has_declared_single_owners() -> None:
    assert {
        contract: tuple(item.name for item in registrations)
        for contract, registrations in CONTRACT_ADAPTER_REGISTRY.items()
    } == {
        "planning_adaptation_facet": (
            "planning_facet_closed_truth",
            "planning_facet_unique_evidence_quote",
        ),
        "planning_event_realizations": (
            "planning_event_topology",
        ),
        "planning_semantic_v2": (
            "planning_semantic_unique_envelope",
            "planning_semantic_root_projection",
        ),
        "execution_manifest": (
            "execution_manifest_evidence_reference",
        ),
        "reference_distillation_region": (
            "reference_distillation_v2_ledger_alignment",
        ),
    }
    assert {
        item.name
        for registrations in CONTRACT_ADAPTER_REGISTRY.values()
        for item in registrations
        if item.automatic_conversion
    } == {
        "planning_semantic_unique_envelope",
        "planning_semantic_root_projection",
        "reference_distillation_v2_ledger_alignment",
    }
    source_root = Path(__file__).parents[1] / "src" / "novel_flywheel"
    workflow_source = (source_root / "workflows.py").read_text(encoding="utf-8")
    assert "def _normalize_current_planning_adaptation_facet_semantics" not in (
        workflow_source
    )
    owners = [
        path.name for path in source_root.glob("*.py")
        if "invariant_truth_set_expanded" in path.read_text(encoding="utf-8")
    ]
    assert owners == ["generated_artifacts.py"]

    quote_owners = [
        path.name for path in source_root.glob("*.py")
        if "unique_evidence_quote_aligned" in path.read_text(encoding="utf-8")
    ]
    assert quote_owners == ["generated_artifacts.py"]

    topology_owners = [
        path.name for path in source_root.glob("*.py")
        if "planning_event_topology_aligned" in path.read_text(encoding="utf-8")
    ]
    assert topology_owners == ["generated_artifacts.py"]
    assert workflow_source.count(
        "_normalize_generated_short_plan_segment("
    ) == 1  # historical parser definition only; no live model-output caller
    assert "allow_legacy_missing" not in workflow_source
    assert "legacy-planning-display" not in workflow_source


@pytest.mark.parametrize("ordered_fields", (
    ["event_function", "primary_actor_agency", "causal_dependencies"],
    ["causal_dependencies", "event_function", "primary_actor_agency"],
    ["PRIMARY_ACTOR_AGENCY", "causal_dependencies", "event_function"],
    ["ｅｖｅｎｔ＿ｆｕｎｃｔｉｏｎ", "primary_actor_agency", "causal_dependencies"],
))
def test_closed_truth_adapter_is_permutation_and_unicode_invariant(
    ordered_fields: list[str],
) -> None:
    requested = (
        "event_function", "primary_actor_agency", "causal_dependencies",
    )
    payload = {
        "invariants": ordered_fields,
        "changed_dimensions": ["presentation_emphasis"],
        "plan_evidence_ids": ["E-1"],
        "reason": "跨题材自由说明保持原样。",
    }

    result = adapt_registered_contract(
        payload,
        contract_name="planning_adaptation_facet",
        context={"invariant_fields": requested},
    )

    assert result.payload["invariants"] == {
        field: True for field in requested
    }
    assert result.payload["reason"] == payload["reason"]
    assert result.audits[0].transformations == (
        "invariant_truth_set_expanded",
    )
    audit_text = result.audits[0].model_dump_json()
    assert payload["reason"] not in audit_text


def test_closed_truth_adapter_can_prove_both_registered_equivalences() -> None:
    requested = (
        "event_function", "primary_actor_agency", "causal_dependencies",
    )
    result = adapt_registered_contract(
        {
            "invariants": list(requested),
            "changed_dimensions": list(reversed(requested)),
            "plan_evidence_ids": ["E-1"],
            "reason": "All invariants remain true.",
        },
        contract_name="planning_adaptation_facet",
        context={"invariant_fields": requested},
    )

    assert result.payload["changed_dimensions"] == []
    assert result.audits[0].transformations == (
        "invariant_truth_set_expanded",
        "reviewed_dimensions_reclassified",
    )
    assert len(result.audits[0].proof_sha256) == 64


def test_closed_truth_adapter_is_idempotent_after_canonicalization() -> None:
    requested = (
        "event_function", "primary_actor_agency", "causal_dependencies",
    )
    first = adapt_registered_contract(
        {
            "invariants": list(reversed(requested)),
            "changed_dimensions": list(requested),
            "plan_evidence_ids": ["E-1"],
            "reason": "Equivalent representation.",
        },
        contract_name="planning_adaptation_facet",
        context={"invariant_fields": requested},
    )

    second = adapt_registered_contract(
        first.payload,
        contract_name="planning_adaptation_facet",
        context={"invariant_fields": requested},
    )

    assert second.payload == first.payload
    assert second.audits == ()


@pytest.mark.parametrize(("source", "fuzzy_quote"), (
    (
        "The archivist opens the sealed registry before sunset and records every transfer.",
        "The archivist opens the sealed registry ... and records every transfer.",
    ),
    (
        "巡夜人先核对城门交接记录，再把缺失的时刻逐项写入值守册。",
        "巡夜人先核对城门交接记录……再把缺失的时刻写入值守册。",
    ),
))
def test_unique_evidence_adapter_proves_extractively_across_narratives(
    source: str, fuzzy_quote: str,
) -> None:
    requested = ("state_continuity", "causal_dependencies")
    payload = {
        "invariants": {
            "state_continuity": False,
            "causal_dependencies": True,
        },
        "changed_dimensions": ["state_continuity"],
        "plan_evidence_ids": ["E-1"],
        "plan_evidence_quote": fuzzy_quote,
        "reason": "The selected state transition conflicts with the invariant.",
    }

    result = adapt_registered_contract(
        payload,
        contract_name="planning_adaptation_facet",
        context={
            "invariant_fields": requested,
            "evidence_candidates": {"E-1": source},
        },
    )

    exact = result.payload["plan_evidence_quote"]
    assert exact in source
    assert result.payload["reason"].startswith(payload["reason"])
    assert exact in result.payload["reason"]
    assert result.audits[0].transformations == (
        "unique_evidence_quote_aligned",
        "runtime_evidence_binding_attached",
    )
    assert source not in result.audits[0].model_dump_json()

    second = adapt_registered_contract(
        result.payload,
        contract_name="planning_adaptation_facet",
        context={
            "invariant_fields": requested,
            "evidence_candidates": {"E-1": source},
        },
    )
    assert second.payload == result.payload
    assert second.audits == ()


def test_unique_exact_evidence_adapter_attaches_detached_reason_without_guessing() -> None:
    source = "巡夜人核对城门交接记录后，把缺失的时刻逐项写入值守册。"
    payload = {
        "invariants": {"state_continuity": False},
        "changed_dimensions": ["state_continuity"],
        "plan_evidence_ids": ["E-1", "E-2"],
        "plan_evidence_quote": source,
        "reason": "The selected transition conflicts with the invariant.",
    }

    result = adapt_registered_contract(
        payload,
        contract_name="planning_adaptation_facet",
        context={
            "invariant_fields": ("state_continuity",),
            "evidence_candidates": {
                "E-1": "An unrelated but sufficiently long evidence candidate remains here.",
                "E-2": source,
            },
        },
    )

    assert result.payload["plan_evidence_quote"] == source
    assert source in result.payload["reason"]
    assert result.audits[0].adapter_version == 2
    assert result.audits[0].source_shape == (
        "unique exact evidence quote with detached reason"
    )
    assert result.audits[0].transformations == (
        "runtime_evidence_binding_attached",
    )


def test_unique_exact_evidence_adapter_rejects_repeated_selected_source() -> None:
    quote = "A sufficiently informative exact evidence phrase remains unchanged."
    payload = {
        "invariants": {"state_continuity": False},
        "changed_dimensions": ["state_continuity"],
        "plan_evidence_ids": ["E-1"],
        "plan_evidence_quote": quote,
        "reason": "The selected transition conflicts with the invariant.",
    }

    result = adapt_registered_contract(
        payload,
        contract_name="planning_adaptation_facet",
        context={
            "invariant_fields": ("state_continuity",),
            "evidence_candidates": {"E-1": quote + " " + quote},
        },
    )

    assert result.payload == payload
    assert result.audits == ()


def test_planning_facet_adapter_rejects_unrelated_quality_scorecard() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" /
         "planning_facet_quality_scorecard_155ea4c5.json")
        .read_text(encoding="utf-8")
    )
    payload = fixture["generated"]

    result = adapt_registered_contract(
        payload,
        contract_name="planning_adaptation_facet",
        context={
            "invariant_fields": tuple(fixture["invariant_fields"]),
            "evidence_candidates": fixture["evidence_candidates"],
        },
    )

    assert result.payload == payload
    assert result.audits == ()


@pytest.mark.parametrize(("evidence_candidates", "evidence_ids", "quote", "reason"), (
    (
        {"E-1": "the same informative evidence phrase appears here; " * 2},
        ["E-1"],
        "the same informative evidence phrase ... appears here",
        "the same informative evidence phrase ... appears here",
    ),
    (
        {
            "E-1": "The archivist opens the sealed registry before sunset.",
            "E-2": "The archivist records every transfer before sunset.",
        },
        ["E-1", "E-2"],
        "The archivist opens the sealed registry ... The archivist records every transfer before sunset",
        "The archivist opens the sealed registry ... The archivist records every transfer before sunset",
    ),
    ({"E-1": "A short source."}, ["E-1"], "short ... source", "short ... source"),
    ({"E-1": "Known evidence with enough informative words for alignment."}, ["E-X"],
     "Known evidence ... informative words", "Known evidence ... informative words"),
    ({"E-1": "Known evidence with enough informative words for alignment."}, ["E-1"],
     "Known evidence ... informative words", ""),
))
def test_unique_evidence_adapter_rejects_ambiguous_weak_or_unbound_shapes(
    evidence_candidates: dict[str, str], evidence_ids: list[str],
    quote: str, reason: str,
) -> None:
    payload = {
        "invariants": {"state_continuity": False},
        "changed_dimensions": ["state_continuity"],
        "plan_evidence_ids": evidence_ids,
        "plan_evidence_quote": quote,
        "reason": reason,
    }

    result = adapt_registered_contract(
        payload,
        contract_name="planning_adaptation_facet",
        context={
            "invariant_fields": ("state_continuity",),
            "evidence_candidates": evidence_candidates,
        },
    )

    assert result.payload == payload
    assert result.audits == ()


@pytest.mark.parametrize(("invariants", "dimensions"), (
    (["event_function", "primary_actor_agency"], []),
    (["event_function", "primary_actor_agency", "primary_actor_agency"], []),
    (["event_function", "primary_actor_agency", "unknown_dimension"], []),
    (
        ["event_function", "primary_actor_agency", "causal_dependencies"],
        ["event_function"],
    ),
))
def test_closed_truth_adapter_does_not_guess_incomplete_or_conflicting_sets(
    invariants: list[str], dimensions: list[str],
) -> None:
    payload = {
        "invariants": invariants,
        "changed_dimensions": dimensions,
        "plan_evidence_ids": ["E-1"],
        "reason": "Unresolved representation.",
    }

    result = adapt_registered_contract(
        payload,
        contract_name="planning_adaptation_facet",
        context={
            "invariant_fields": (
                "event_function", "primary_actor_agency", "causal_dependencies",
            ),
        },
    )

    assert result.payload == payload
    assert result.audits == ()


def test_p0_no_parallel_model_output_parser_authority_is_reintroduced() -> None:
    source_root = Path(__file__).parents[1] / "src" / "novel_flywheel"
    remaining = {}
    for path in source_root.rglob("*.py"):
        if "baml_client" in path.parts:
            continue
        count = path.read_text(encoding="utf-8").count("parse_json_object(")
        if count:
            remaining[path.relative_to(source_root).as_posix()] = count

    assert remaining == {
        "generated_artifacts.py": 1,
        "model_output.py": 1,
    }


def test_p0_business_services_cannot_own_direct_model_dispatch() -> None:
    source_root = Path(__file__).parents[1] / "src" / "novel_flywheel"
    owners: dict[str, set[str]] = {}
    for path in source_root.rglob("*.py"):
        if "baml_client" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            target = node.func.value
            if (
                isinstance(target, ast.Attribute)
                and target.attr == "gateway"
                and node.func.attr.startswith("complete")
            ):
                owners.setdefault(
                    path.relative_to(source_root).as_posix(), set(),
                ).add(node.func.attr)

    assert owners == {}


def test_p0_deleted_business_parser_shadows_cannot_return() -> None:
    """Historical readers live in the registry, never beside each service."""

    source_root = Path(__file__).parents[1] / "src" / "novel_flywheel"
    forbidden = {
        "style_samples.py": {"_parse_profile"},
        "material_impacts.py": {"_json_object"},
        "interviews.py": {"_parse_output"},
        "learning.py": {"_json_object"},
        "workflows.py": {"_json_object"},
    }
    discovered = set()
    for filename, names in forbidden.items():
        tree = ast.parse(
            (source_root / filename).read_text(encoding="utf-8"),
            filename=filename,
        )
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name in names:
                    discovered.add((filename, node.name))
    assert discovered == set()


def test_p0_every_structured_business_boundary_uses_a_registered_contract() -> None:
    def static_contract_names(value: ast.expr) -> set[str] | None:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return {value.value}
        if isinstance(value, ast.IfExp):
            left = static_contract_names(value.body)
            right = static_contract_names(value.orelse)
            return None if left is None or right is None else left | right
        return None

    source_root = Path(__file__).parents[1] / "src" / "novel_flywheel"
    discovered: list[tuple[str, int, str]] = []
    for path in source_root.rglob("*.py"):
        if "baml_client" in path.parts:
            continue
        if path.name in {"contract_runtime.py", "generated_artifacts.py"}:
            # These two infrastructure owners are deliberately parameterized;
            # business callers must select the registered contract literally.
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else node.func.attr if isinstance(node.func, ast.Attribute) else ""
            )
            if name not in {
                "convert_object", "execute_contract_runtime",
                "_convert_generated_object",
            }:
                continue
            keyword = next(
                (item for item in node.keywords if item.arg == "contract_name"),
                None,
            )
            assert keyword is not None, f"{path}:{node.lineno} has no contract_name"
            contract_names = static_contract_names(keyword.value)
            if contract_names is None:
                is_workflow_conversion_owner = (
                    path.name == "workflows.py"
                    and isinstance(keyword.value, ast.Name)
                    and keyword.value.id == "contract_name"
                    and any(
                        function.name == "_convert_generated_object"
                        and node in ast.walk(function)
                        for function in ast.walk(tree)
                        if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
                    )
                )
                is_workflow_stage_runtime_owner = (
                    path.name == "workflows.py"
                    and isinstance(keyword.value, ast.Attribute)
                    and keyword.value.attr == "name"
                    and isinstance(keyword.value.value, ast.Name)
                    and keyword.value.value.id == "structured_contract"
                    and any(
                        function.name == "_stage"
                        and node in ast.walk(function)
                        for function in ast.walk(tree)
                        if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
                    )
                )
                assert (
                    is_workflow_conversion_owner
                    or is_workflow_stage_runtime_owner
                ), (
                    f"{path}:{node.lineno} uses a dynamic structured contract"
                )
                continue
            discovered.extend(
                (
                    path.relative_to(source_root).as_posix(),
                    node.lineno,
                    contract_name,
                )
                for contract_name in contract_names
            )

    assert discovered
    unknown = [item for item in discovered if item[2] not in ARTIFACT_CONTRACT_REGISTRY]
    assert unknown == []


def test_static_runtime_wire_contract_versions_match_registered_business_contracts() -> None:
    """Catch a wrong contract/wire pairing before a long-running task starts."""

    source_root = Path(__file__).parents[1] / "src" / "novel_flywheel"
    checked = []
    for path in source_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        wire_versions = {}
        for node in tree.body:
            if not (
                isinstance(node, (ast.Assign, ast.AnnAssign))
                and isinstance(node.value, ast.Call)
                and (
                    (isinstance(node.value.func, ast.Name)
                     and node.value.func.id == "StructuredArtifactContract")
                    or (isinstance(node.value.func, ast.Attribute)
                        and node.value.func.attr == "StructuredArtifactContract")
                )
            ):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            version = next(
                (
                    keyword.value.value
                    for keyword in node.value.keywords
                    if keyword.arg == "version"
                    and isinstance(keyword.value, ast.Constant)
                    and isinstance(keyword.value.value, int)
                ),
                None,
            )
            for target in targets:
                if isinstance(target, ast.Name) and version is not None:
                    wire_versions[target.id] = version

        for call in ast.walk(tree):
            if not (
                isinstance(call, ast.Call)
                and (
                    (isinstance(call.func, ast.Name)
                     and call.func.id == "execute_contract_runtime")
                    or (isinstance(call.func, ast.Attribute)
                        and call.func.attr == "execute_contract_runtime")
                )
            ):
                continue
            contract_keyword = next(
                (item for item in call.keywords if item.arg == "contract_name"),
                None,
            )
            wire_keyword = next(
                (item for item in call.keywords if item.arg == "structured_contract"),
                None,
            )
            if not (
                contract_keyword is not None
                and isinstance(contract_keyword.value, ast.Constant)
                and isinstance(contract_keyword.value.value, str)
                and wire_keyword is not None
                and isinstance(wire_keyword.value, ast.Name)
                and wire_keyword.value.id in wire_versions
            ):
                continue
            contract_name = contract_keyword.value.value
            wire_version = wire_versions[wire_keyword.value.id]
            checked.append((
                path.relative_to(source_root).as_posix(), call.lineno,
                contract_name, wire_version,
            ))
            assert ARTIFACT_CONTRACT_REGISTRY[contract_name].version == wire_version

    assert checked


def test_reference_window_model_calls_have_one_specific_executable_contract() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "novel_flywheel" / "learning.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    method = next(
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "model_analyze_reference"
    )
    contracts = []
    for node in ast.walk(method):
        if not isinstance(node, ast.Call):
            continue
        name = (
            node.func.id if isinstance(node.func, ast.Name)
            else node.func.attr if isinstance(node.func, ast.Attribute) else ""
        )
        if name != "execute_contract_runtime":
            continue
        keyword = next(item for item in node.keywords if item.arg == "contract_name")
        assert isinstance(keyword.value, ast.Constant)
        contracts.append(keyword.value.value)

    assert contracts.count("reference_analysis_window") == 2
    assert contracts.count("reference_distillation_region") == 1
    assert "learning_artifact" not in contracts


@pytest.mark.parametrize("container", ["steps", "causal_cycles"])
def test_baml_sap_aligns_real_provider_cycle_containers_without_alias_rules(container) -> None:
    raw = json.dumps({
        container: [_cycle()],
        "covered_event_ids": ["EV-1"],
        "ending": "只有末包可拥有的结尾",
    }, ensure_ascii=False)

    result = GeneratedArtifactGateway().convert_object(
        raw, contract_name="short_causal_chain",
        semantic_normalizer=_normalizer(owns_ending=False),
        expected_event_ids=("EV-1",), owns_ending=False,
    )

    assert result.payload["cycles"] == [_cycle()]
    assert result.payload["ending"] == ""
    assert result.audit.method == "baml_sap"
    assert "$.ending" in result.audit.quarantined_paths
    assert result.audit.semantic_valid is True


def test_baml_sap_aligns_unseen_nested_wrapper_by_topology() -> None:
    raw = json.dumps({
        "delivery": {"narrative_motion": [_cycle()]},
        "ownership": ["EV-1"],
    }, ensure_ascii=False)

    result = GeneratedArtifactGateway().convert_object(
        raw, contract_name="short_causal_chain",
        semantic_normalizer=_normalizer(), expected_event_ids=("EV-1",),
    )

    assert result.payload["covered_event_ids"] == ["EV-1"]
    assert result.payload["cycles"][0]["state_change"] == "取得新线索"


def test_ambiguous_cycle_topologies_fail_closed_for_protocol_retry() -> None:
    raw = json.dumps({
        "candidate_a": [_cycle()],
        "candidate_b": [_cycle(result="另一个互斥结果")],
        "covered_event_ids": ["EV-1"],
    }, ensure_ascii=False)

    with pytest.raises(ArtifactConversionError) as caught:
        GeneratedArtifactGateway().convert_object(
            raw, contract_name="short_causal_chain",
            semantic_normalizer=_normalizer(), expected_event_ids=("EV-1",),
        )

    assert caught.value.audit.failure_code == "ambiguous_structural_candidates"
    assert caught.value.audit.candidate_count == 2


def test_local_syntax_repair_still_requires_semantic_validation() -> None:
    raw = '{"cycles": [{"obstacle":"o","effort":"e","result":"r","state_change":"s",}], "covered_event_ids":["EV-1"],}'

    result = GeneratedArtifactGateway().convert_object(
        raw, contract_name="short_causal_chain",
        semantic_normalizer=_normalizer(), expected_event_ids=("EV-1",),
    )

    assert result.audit.method == "local_syntax_repair"
    assert result.audit.semantic_valid is True


def test_truncated_incomplete_payload_is_not_mistaken_for_recovery() -> None:
    raw = '{"cycles": [{"obstacle":"o","effort":"e"'

    with pytest.raises(ArtifactConversionError) as caught:
        GeneratedArtifactGateway().convert_object(
            raw, contract_name="short_causal_chain",
            semantic_normalizer=_normalizer(), expected_event_ids=("EV-1",),
        )

    assert caught.value.audit.failure_code == "output_truncated"


def test_conversion_audit_is_content_addressed_and_does_not_store_raw_text(tmp_path) -> None:
    secret_marker = "never-persist-this-raw-marker"
    raw = json.dumps({
        "cycles": [_cycle()], "covered_event_ids": ["EV-1"],
        "description": secret_marker,
    })
    result = GeneratedArtifactGateway().convert_object(
        raw, contract_name="short_causal_chain",
        semantic_normalizer=_normalizer(), expected_event_ids=("EV-1",),
    )

    path = write_conversion_audit(tmp_path, result.audit)
    stored = path.read_text(encoding="utf-8")

    assert secret_marker not in stored
    assert result.audit.raw_sha256 in stored
    assert write_conversion_audit(tmp_path, result.audit) == path
