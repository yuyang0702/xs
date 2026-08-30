from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import novel_flywheel.planning_closure as planning_closure_module
import novel_flywheel.planning_semantics as planning_semantics_module
import novel_flywheel.style_context as style_context_module

from novel_flywheel.contract_runtime import (
    ExecutableContractSpec,
    execute_contract_runtime,
)
from novel_flywheel.models import ModelResult
from novel_flywheel.outlines import narrative_outline_event_contracts
from novel_flywheel.prose_quality import (
    AuthorityTermProjectionFieldV1,
    AuthorityTermSourceArtifactV1,
    DraftProseAuthorityContextV1,
    analyze_prose,
    build_authority_approved_latin_term_set,
)
from novel_flywheel.structured_artifacts import StructuredArtifactContract
from novel_flywheel.planning_semantics import (
    PlanningSemanticFindingContractError,
    extract_planning_semantic_v2_findings,
    normalize_planning_semantic_v2_payload,
    render_actionable_planning_semantic_findings,
    planning_semantic_schema_v2,
    PlanningSemanticDraftV2,
    compile_planning_semantic_v2,
    merge_planning_semantic_event_packets_v2,
    merge_planning_semantic_document_packets_v2,
    parse_planning_semantic_v2,
    planning_semantic_packet_ownership_v2,
)
from novel_flywheel.planning_closure import (
    PlanningGlobalClosureError,
    build_runtime_planning_global_closure,
    compute_planning_global_closure,
)
from novel_flywheel.style_context import (
    final_review_style_reference_receipt,
    selected_style_reference_provenance,
    render_selected_style_reference_context,
    validate_style_reference_context_receipt,
)
from novel_flywheel.workflows import (
    DraftRetryFindingContractError,
    DraftRetryFindingV1,
    apply_draft_local_repair_units,
    build_draft_retry_findings,
    build_draft_local_repair_units,
    normalize_draft_local_repair_contract,
    render_actionable_draft_validation_findings,
    validate_draft_local_repair_replacement,
    WorkflowService,
)


SHA = "a" * 64
FIXTURE = (
    Path(__file__).parent / "fixtures" / "reliability"
    / "short_trustworthy_full_flow" / "sanitized-isomorphic-fixture-v1.json"
)


def _valid_semantic_payload() -> dict:
    return {
        "version": 2,
        "initial_state": "雨夜里所有人仍在站台等待",
        "segments": [
            {
                "kind": "terminal",
                "segment": 1,
                "title": "最后一班车",
                "events": [
                    {
                        "formal_event_ordinal": 1,
                        "narrative": "林澈顶着人群质疑查清车票去向并决定留下证据",
                    }
                ],
            }
        ],
    }


def _semantic_variant(kind: str) -> tuple[object, list[dict], int]:
    events = [
        {"id": "EV-00000001", "label": "发现车票", "evidence": "林澈发现被替换的车票并保存证据。"},
        {"id": "EV-00000002", "label": "公开证据", "evidence": "林澈公开证据迫使站长回应。"},
    ]
    if kind in {"single", "wrapped_single"}:
        payload = _valid_semantic_payload()
        return ({"result": {"artifact": payload}} if kind == "wrapped_single" else payload), events[:1], 1
    if kind == "one_segment_two_events":
        payload = _valid_semantic_payload()
        payload["segments"][0]["events"].append({
            "formal_event_ordinal": 2,
            "narrative": "林澈把证据投到屏幕上迫使站长承认换票并交代后果",
        })
        return payload, events, 1
    payload = {
        "version": 2,
        "initial_state": "雨夜里所有人仍在站台等待",
        "segments": [
            {
                "kind": "continuation", "segment": 1, "title": "追查车票",
                "events": [{
                    "formal_event_ordinal": 1,
                    "narrative": "林澈顶着质疑查清车票去向并把原票保存在证物袋里",
                }],
                "exit_state": "林澈已经掌握原票并准备向所有候车人公开证据",
            },
            {
                "kind": "terminal", "segment": 2, "title": "公开真相",
                "events": [{
                    "formal_event_ordinal": 1 if kind == "shared_ordinal" else 2,
                    "narrative": "林澈当众展示票据逼迫站长回应并承担换票造成的后果",
                }],
            },
        ],
    }
    formal = events[:1] if kind == "shared_ordinal" else events
    if kind == "wrapped_two_segments":
        return {"payload": {"semantic_candidate": payload}}, formal, 2
    if kind == "descriptor_projection":
        payload["exit_state"] = "Packet-level descriptive echo only."
    return payload, formal, 2


@pytest.mark.parametrize(
    "kind",
    [
        "single", "wrapped_single", "one_segment_two_events",
        "two_segments", "wrapped_two_segments", "shared_ordinal",
        "descriptor_projection",
    ],
)
def test_planning_open_world_valid_variants_cross_the_compiler(kind: str) -> None:
    raw_value, events, segment_count = _semantic_variant(kind)
    semantic, audit = parse_planning_semantic_v2(
        json.dumps(raw_value, ensure_ascii=False)
    )
    compiled = compile_planning_semantic_v2(
        semantic,
        events,
        formal_ending={"evidence": events[-1]["evidence"]},
        expected_segment_count=segment_count,
        conversion_audit=audit,
    )
    assert compiled.document.authority_sha256
    assert compiled.exit_topology.authority_sha256


def test_planning_open_world_unknown_and_ambiguous_shapes_fail_closed() -> None:
    unknown = _valid_semantic_payload()
    unknown["routing_mode"] = "skip_validation"
    with pytest.raises(ValueError):
        parse_planning_semantic_v2(json.dumps(unknown, ensure_ascii=False))
    with pytest.raises(ValueError):
        parse_planning_semantic_v2(json.dumps({
            "first": _valid_semantic_payload(),
            "second": _valid_semantic_payload(),
        }, ensure_ascii=False))


def test_planning_open_world_truncated_capacity_shape_fails_closed() -> None:
    raw = json.dumps(_valid_semantic_payload(), ensure_ascii=False)
    with pytest.raises(ValueError):
        parse_planning_semantic_v2(raw[: len(raw) // 2])


def test_planning_semantic_findings_are_typed_bounded_and_replay_deterministic() -> None:
    invalid = _valid_semantic_payload()
    invalid["segments"][0]["events"][0]["formal_event_ordinal"] = "1"
    invalid["segments"][0]["unexpected"] = "must fail closed"

    first = extract_planning_semantic_v2_findings(invalid)
    second = extract_planning_semantic_v2_findings(json.loads(json.dumps(invalid)))

    assert first == second
    assert {item["finding_code"] for item in first} == {
        "strict_integer_required",
        "extra_field_forbidden",
    }
    assert all(item["owner"] == "planning_semantic_v2.model_payload" for item in first)
    assert all("input" not in item and "raw" not in item for item in first)
    assert all(len(item["finding_identity_sha256"]) == 64 for item in first)

    rendered = render_actionable_planning_semantic_findings(
        first,
        {
            "contract_name": "planning_semantic_v2",
            "repair_target_identity_sha256": SHA,
        },
        first.source_payload_sha256,
    )
    assert "ACTIONABLE_PLANNING_SEMANTIC_FINDINGS" in rendered
    assert "strict_integer_required" in rendered
    assert "must fail closed" not in rendered
    assert len(rendered.encode("utf-8")) <= 8192


def test_planning_semantic_normalizer_keeps_invalid_candidate_for_domain_findings() -> None:
    invalid = {"version": 2, "segments": []}
    assert normalize_planning_semantic_v2_payload(invalid) == invalid
    assert normalize_planning_semantic_v2_payload({"result": invalid}) is None


def test_planning_semantic_renderer_rejects_tampered_finding() -> None:
    invalid = _valid_semantic_payload()
    invalid["segments"] = []
    finding = dict(extract_planning_semantic_v2_findings(invalid)[0])
    finding["field_path"] = "/segments/99"
    with pytest.raises(PlanningSemanticFindingContractError):
        render_actionable_planning_semantic_findings(
            [finding],
            {
                "contract_name": "planning_semantic_v2",
                "repair_target_identity_sha256": SHA,
            },
            "b" * 64,
        )


def test_planning_semantic_renderer_rejects_authentic_batch_with_wrong_source() -> None:
    invalid = _valid_semantic_payload()
    invalid["version"] = "2"
    findings = extract_planning_semantic_v2_findings(invalid)

    with pytest.raises(PlanningSemanticFindingContractError):
        render_actionable_planning_semantic_findings(
            findings,
            {
                "contract_name": "planning_semantic_v2",
                "repair_target_identity_sha256": SHA,
            },
            "b" * 64,
        )


def test_planning_semantic_validator_batch_source_binding_is_immutable() -> None:
    invalid = _valid_semantic_payload()
    invalid["version"] = "2"
    findings = extract_planning_semantic_v2_findings(invalid)

    with pytest.raises((AttributeError, TypeError)):
        findings.source_payload_sha256 = "b" * 64
    with pytest.raises((AttributeError, TypeError)):
        findings._validator_signature = "c" * 64
    with pytest.raises(TypeError):
        findings[0]["field_path"] = "/retargeted"
    assert not hasattr(findings, "__dict__")


def test_planning_semantic_validator_batch_rejects_replayed_signature_forgery() -> None:
    invalid = _valid_semantic_payload()
    invalid["segments"][0]["kind"] = "unknown"
    findings = extract_planning_semantic_v2_findings(invalid)
    original = dict(findings[0])
    retargeted = _reauthorize_finding(
        original, field_path="/segments/999/attacker_retarget",
    )
    replayed_signature = tuple.__getitem__(findings, 2)
    forged = planning_semantics_module.PlanningSemanticFindingBatch(
        [retargeted],
        source_payload_sha256=findings.source_payload_sha256,
        _signature=replayed_signature,
    )
    with pytest.raises(PlanningSemanticFindingContractError):
        render_actionable_planning_semantic_findings(
            forged,
            {
                "contract_name": "planning_semantic_v2",
                "repair_target_identity_sha256": SHA,
            },
            findings.source_payload_sha256,
        )


def _reauthorize_finding(finding: dict, **changes: object) -> dict:
    candidate = {**finding, **changes}
    candidate.pop("finding_identity_sha256", None)
    candidate["finding_identity_sha256"] = hashlib.sha256(json.dumps(
        candidate, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()
    return candidate


def test_planning_semantic_renderer_rejects_rehashed_unknown_and_reason_mismatch() -> None:
    invalid = _valid_semantic_payload()
    invalid["version"] = "2"
    finding = dict(extract_planning_semantic_v2_findings(invalid)[0])
    unknown = _reauthorize_finding(
        finding, finding_code="unregistered_finding",
    )
    wrong_reason = _reauthorize_finding(
        finding, validator_reason_code="extra_forbidden",
    )
    for candidate in (unknown, wrong_reason):
        with pytest.raises(PlanningSemanticFindingContractError):
            render_actionable_planning_semantic_findings(
                [candidate],
                {
                    "contract_name": "planning_semantic_v2",
                    "repair_target_identity_sha256": SHA,
                },
                "b" * 64,
            )


def test_planning_semantic_renderer_rejects_rehashed_registered_path_retarget() -> None:
    invalid = _valid_semantic_payload()
    invalid["segments"][0]["kind"] = "unknown"
    finding = dict(extract_planning_semantic_v2_findings(invalid)[0])
    retargeted = _reauthorize_finding(
        finding, field_path="/segments/999/attacker_retarget",
    )

    with pytest.raises(PlanningSemanticFindingContractError):
        render_actionable_planning_semantic_findings(
            [retargeted],
            {
                "contract_name": "planning_semantic_v2",
                "repair_target_identity_sha256": SHA,
            },
            "b" * 64,
        )


def test_planning_semantic_renderer_rejects_exact_duplicate_findings() -> None:
    invalid = _valid_semantic_payload()
    invalid["version"] = "2"
    finding = extract_planning_semantic_v2_findings(invalid)[0]
    with pytest.raises(PlanningSemanticFindingContractError):
        render_actionable_planning_semantic_findings(
            [finding, dict(finding)],
            {
                "contract_name": "planning_semantic_v2",
                "repair_target_identity_sha256": SHA,
            },
            "b" * 64,
        )


def test_every_registered_planning_finding_kind_is_canonical_and_distinct() -> None:
    findings = []
    for index, (reason, (code, scope)) in enumerate(sorted(
        planning_semantics_module._PLANNING_SEMANTIC_FINDING_REGISTRY.items()
    )):
        base = {
            "schema": "PlanningSemanticFindingV1", "version": 1,
            "finding_code": code, "validator_reason_code": reason,
            "field_path": f"/segments/{index}",
            "owner": "planning_semantic_v2.model_payload",
            "authority_status": "rejected",
            "contract_name": "planning_semantic_v2", "contract_version": 2,
            "repair_scope_kind": scope,
        }
        findings.append(_reauthorize_finding(base))
    assert all(
        planning_semantics_module._planning_semantic_finding_contract(
            finding["validator_reason_code"]
        ) == (finding["finding_code"], finding["repair_scope_kind"])
        for finding in findings
    )
    assert len({item["finding_identity_sha256"] for item in findings}) == len(
        findings
    )


def test_planning_finding_closed_schema_rejects_sha_and_extra_field_tampering() -> None:
    invalid = _valid_semantic_payload()
    invalid["version"] = "2"
    finding = dict(extract_planning_semantic_v2_findings(invalid)[0])
    candidates = [
        {**finding, "finding_identity_sha256": "not-a-sha"},
        {**finding, "field_path": "/changed"},
        {**finding, "critical": True},
    ]
    for candidate in candidates:
        with pytest.raises(PlanningSemanticFindingContractError):
            render_actionable_planning_semantic_findings(
                [candidate],
                {
                    "contract_name": "planning_semantic_v2",
                    "repair_target_identity_sha256": SHA,
                },
                "b" * 64,
            )


@pytest.mark.asyncio
async def test_planning_typed_finding_reaches_the_next_bounded_attempt() -> None:
    invalid = _valid_semantic_payload()
    invalid["segments"][0]["events"][0]["formal_event_ordinal"] = "1"
    valid = _valid_semantic_payload()
    calls: list[str] = []

    async def execute(attempt, role, system, user, max_output_tokens, contract):
        calls.append(user)
        payload = invalid if len(calls) == 1 else valid
        return ModelResult(
            json.dumps(payload, ensure_ascii=False),
            {"finish_reason": "end_turn", "model_name": "offline-fake"},
        )

    spec = ExecutableContractSpec(
        contract_name="planning_semantic_v2",
        structured_contract=StructuredArtifactContract(
            name="planning_semantic_v2",
            version=2,
            schema=planning_semantic_schema_v2(),
            runtime_authority={"repair_target_identity_sha256": SHA},
        ),
        semantic_normalizer=normalize_planning_semantic_v2_payload,
        domain_validator=PlanningSemanticDraftV2.model_validate,
        domain_diagnostic_extractor=extract_planning_semantic_v2_findings,
        domain_diagnostic_metadata={
            "contract_name": "planning_semantic_v2",
            "repair_target_identity_sha256": SHA,
        },
        domain_retry_renderer=render_actionable_planning_semantic_findings,
        retry_domain_failures=True,
    )
    result = await execute_contract_runtime(
        SimpleNamespace(),
        role="planning",
        system="sealed system",
        user="sealed task",
        execution_spec=spec,
        attempt_routes=("primary", "primary"),
        attempt_executor=execute,
    )
    assert result.payload == valid
    assert len(calls) == 2
    assert "ACTIONABLE_PLANNING_SEMANTIC_FINDINGS" not in calls[0]
    assert "strict_integer_required" in calls[1]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("missing_fields", "expected_paths"),
    [
        (("initial_state",), ("/initial_state",)),
        (("segments",), ("/segments",)),
        (
            ("initial_state", "segments"),
            ("/initial_state", "/segments"),
        ),
    ],
)
async def test_planning_missing_root_fields_reach_typed_bounded_recovery(
    missing_fields: tuple[str, ...], expected_paths: tuple[str, ...],
) -> None:
    incomplete = _valid_semantic_payload()
    for field in missing_fields:
        incomplete.pop(field)
    valid = _valid_semantic_payload()
    calls: list[str] = []
    local_rejections: list[dict] = []

    async def execute(attempt, role, system, user, max_output_tokens, contract):
        calls.append(user)
        payload = incomplete if len(calls) == 1 else valid
        return ModelResult(
            json.dumps(payload, ensure_ascii=False),
            {"finish_reason": "end_turn", "model_name": "offline-fake"},
        )

    spec = ExecutableContractSpec(
        contract_name="planning_semantic_v2",
        structured_contract=StructuredArtifactContract(
            name="planning_semantic_v2", version=2,
            schema=planning_semantic_schema_v2(),
            runtime_authority={"repair_target_identity_sha256": SHA},
        ),
        semantic_normalizer=normalize_planning_semantic_v2_payload,
        domain_validator=PlanningSemanticDraftV2.model_validate,
        domain_diagnostic_extractor=extract_planning_semantic_v2_findings,
        domain_diagnostic_metadata={
            "contract_name": "planning_semantic_v2",
            "repair_target_identity_sha256": SHA,
        },
        domain_retry_renderer=render_actionable_planning_semantic_findings,
        retry_domain_failures=True,
    )
    result = await execute_contract_runtime(
        SimpleNamespace(), role="planning", system="sealed", user="task",
        execution_spec=spec, attempt_routes=("primary", "primary"),
        attempt_executor=execute,
        local_rejection_sink=local_rejections.append,
    )

    assert result.payload == valid
    assert len(calls) == 2
    assert all(path in calls[1] for path in expected_paths)
    assert "required_field_missing" in calls[1]
    assert len(local_rejections) == 1
    assert local_rejections[0]["failure_kind"] == "domain_validation"
    assert local_rejections[0]["raw_content_persisted"] is False
    assert "response_text" not in local_rejections[0]


def test_schema_valid_planning_authority_failure_emits_typed_finding() -> None:
    payload = _valid_semantic_payload()
    payload["segments"][0]["events"][0]["formal_event_ordinal"] = 2
    events = [{
        "id": "EV-00000001", "label": "发现车票",
        "evidence": "林澈发现被替换的车票并保存证据。",
    }]

    def validate(candidate: object) -> object:
        semantic = PlanningSemanticDraftV2.model_validate(candidate)
        return compile_planning_semantic_v2(
            semantic, events,
            formal_ending={"evidence": events[-1]["evidence"]},
            expected_segment_count=1,
        )

    findings = extract_planning_semantic_v2_findings(
        payload, domain_validator=validate,
    )
    assert len(findings) == 1
    assert findings[0]["finding_code"] == "event_ordinal_outside_authority"
    assert findings[0]["repair_scope_kind"] == "field_local"
    assert findings[0]["field_path"] == (
        "/segments/events/formal_event_ordinal"
    )


@pytest.mark.asyncio
async def test_planning_retry_source_identity_binds_rejected_candidate() -> None:
    async def source_for(initial: dict) -> str:
        valid = _valid_semantic_payload()
        calls: list[str] = []

        async def execute(attempt, role, system, user, max_output_tokens, contract):
            calls.append(user)
            payload = initial if len(calls) == 1 else valid
            return ModelResult(
                json.dumps(payload, ensure_ascii=False),
                {"finish_reason": "end_turn", "model_name": "offline-fake"},
            )

        spec = ExecutableContractSpec(
            contract_name="planning_semantic_v2",
            structured_contract=StructuredArtifactContract(
                name="planning_semantic_v2", version=2,
                schema=planning_semantic_schema_v2(),
                runtime_authority={"repair_target_identity_sha256": SHA},
            ),
            semantic_normalizer=normalize_planning_semantic_v2_payload,
            domain_validator=PlanningSemanticDraftV2.model_validate,
            domain_diagnostic_extractor=extract_planning_semantic_v2_findings,
            domain_diagnostic_metadata={
                "contract_name": "planning_semantic_v2",
                "repair_target_identity_sha256": SHA,
            },
            domain_retry_renderer=render_actionable_planning_semantic_findings,
            retry_domain_failures=True,
        )
        await execute_contract_runtime(
            SimpleNamespace(), role="planning", system="sealed", user="task",
            execution_spec=spec, attempt_routes=("primary", "primary"),
            attempt_executor=execute,
        )
        retry = calls[1]
        return retry.split('"source_identity_sha256":"', 1)[1].split('"', 1)[0]

    wrong_version = _valid_semantic_payload()
    wrong_version["version"] = "2"
    wrong_ordinal = _valid_semantic_payload()
    wrong_ordinal["segments"][0]["events"][0]["formal_event_ordinal"] = "1"
    assert await source_for(wrong_version) != await source_for(wrong_ordinal)


@pytest.mark.asyncio
async def test_schema_valid_packet_ownership_failure_retries_with_typed_finding() -> None:
    invalid = _valid_semantic_payload()
    invalid["segments"][0]["events"][0]["formal_event_ordinal"] = 2
    valid = _valid_semantic_payload()
    calls: list[str] = []

    def validate(payload: object) -> object:
        packet = PlanningSemanticDraftV2.model_validate(payload)
        return merge_planning_semantic_event_packets_v2([packet], [(1,)])

    async def execute(attempt, role, system, user, max_output_tokens, contract):
        calls.append(user)
        payload = invalid if len(calls) == 1 else valid
        return ModelResult(
            json.dumps(payload, ensure_ascii=False),
            {"finish_reason": "end_turn", "model_name": "offline-fake"},
        )

    spec = ExecutableContractSpec(
        contract_name="planning_semantic_v2",
        structured_contract=StructuredArtifactContract(
            name="planning_semantic_v2", version=2,
            schema=planning_semantic_schema_v2(),
            runtime_authority={"repair_target_identity_sha256": SHA},
        ),
        semantic_normalizer=normalize_planning_semantic_v2_payload,
        domain_validator=validate,
        domain_diagnostic_extractor=lambda payload: (
            extract_planning_semantic_v2_findings(
                payload, domain_validator=validate,
            )
        ),
        domain_diagnostic_metadata={
            "contract_name": "planning_semantic_v2",
            "repair_target_identity_sha256": SHA,
        },
        domain_retry_renderer=render_actionable_planning_semantic_findings,
        retry_domain_failures=True,
    )
    result = await execute_contract_runtime(
        SimpleNamespace(), role="planning", system="sealed", user="task",
        execution_spec=spec, attempt_routes=("primary", "primary"),
        attempt_executor=execute,
    )
    assert result.payload == valid
    assert len(calls) == 2
    assert "packet_event_coverage_invalid" in calls[1]


@pytest.mark.parametrize("ordinal", [True, 1.0, "1", None])
def test_packet_merges_reject_non_exact_runtime_owned_ordinal_types(ordinal) -> None:
    packet = PlanningSemanticDraftV2.model_validate(_valid_semantic_payload())
    for merge in (
        lambda: merge_planning_semantic_event_packets_v2(
            [packet], [(ordinal,)],
        ),
        lambda: merge_planning_semantic_document_packets_v2(
            [packet], [(ordinal,)], formal_event_count=1,
        ),
    ):
        with pytest.raises(ValueError, match="ownership ordinal is invalid"):
            merge()


@pytest.mark.parametrize("ordinal", [True, 1.0, "1", None])
def test_packet_merges_revalidate_model_copy_mutated_candidate_ordinals(ordinal) -> None:
    packet = PlanningSemanticDraftV2.model_validate(_valid_semantic_payload())
    segment = packet.segments[0]
    mutated_event = segment.events[0].model_copy(
        update={"formal_event_ordinal": ordinal}
    )
    mutated_segment = segment.model_copy(update={"events": [mutated_event]})
    mutated_packet = packet.model_copy(update={"segments": [mutated_segment]})
    for merge in (
        lambda: merge_planning_semantic_event_packets_v2(
            [mutated_packet], [(1,)],
        ),
        lambda: merge_planning_semantic_document_packets_v2(
            [mutated_packet], [(1,)], formal_event_count=1,
        ),
    ):
        with pytest.raises(ValueError, match="strict canonical data"):
            merge()


@pytest.mark.parametrize("ordinal", [True, 1.0, "1", None])
def test_planning_compiler_revalidates_model_copy_mutated_ordinals(ordinal) -> None:
    semantic = PlanningSemanticDraftV2.model_validate(_valid_semantic_payload())
    segment = semantic.segments[0]
    mutated_event = segment.events[0].model_copy(
        update={"formal_event_ordinal": ordinal}
    )
    mutated = semantic.model_copy(update={
        "segments": [segment.model_copy(update={"events": [mutated_event]})],
    })
    with pytest.raises(ValueError, match="strict canonical data"):
        compile_planning_semantic_v2(
            mutated,
            [{"id": "EV-00000001", "label": "事件", "evidence": "事件证据"}],
            formal_ending={"evidence": "终局证据"},
            expected_segment_count=1,
        )


@pytest.mark.parametrize(
    "group",
    [{1: "ignored"}, {1}, "1", (value for value in [1])],
)
def test_packet_merges_reject_non_sequence_ownership_containers(group) -> None:
    packet = PlanningSemanticDraftV2.model_validate(_valid_semantic_payload())
    for merge in (
        lambda: merge_planning_semantic_event_packets_v2([packet], [group]),
        lambda: merge_planning_semantic_document_packets_v2(
            [packet], [group], formal_event_count=1,
        ),
    ):
        with pytest.raises(ValueError, match="group shape is invalid"):
            merge()


def test_document_packet_merge_rejects_boolean_formal_event_count() -> None:
    packet = PlanningSemanticDraftV2.model_validate(_valid_semantic_payload())
    with pytest.raises(ValueError, match="formal event count is invalid"):
        merge_planning_semantic_document_packets_v2(
            [packet], [(1,)], formal_event_count=True,
        )


@pytest.mark.parametrize("invalid", [True, False, 1.0, "1", None])
def test_planning_packet_ownership_rejects_non_exact_counts(invalid) -> None:
    with pytest.raises(ValueError):
        planning_semantic_packet_ownership_v2(
            segment_count=invalid, formal_event_count=1,
        )
    with pytest.raises(ValueError):
        planning_semantic_packet_ownership_v2(
            segment_count=1, formal_event_count=invalid,
        )


@pytest.mark.parametrize("invalid", [True, False, 1.0, "1", None])
def test_planning_compiler_rejects_non_exact_expected_segment_count(invalid) -> None:
    with pytest.raises(ValueError, match="expected segment count is invalid"):
        compile_planning_semantic_v2(
            PlanningSemanticDraftV2.model_validate(_valid_semantic_payload()),
            [{"id": "EV-00000001", "label": "事件", "evidence": "事件证据"}],
            formal_ending={"evidence": "终局证据"},
            expected_segment_count=invalid,
        )


@pytest.mark.parametrize("bad_id", ["", False, 0, None])
def test_planning_compiler_does_not_truthiness_fallback_to_valid_alias(bad_id) -> None:
    with pytest.raises(ValueError):
        compile_planning_semantic_v2(
            PlanningSemanticDraftV2.model_validate(_valid_semantic_payload()),
            [{
                "id": bad_id, "event_id": "EV-00000001",
                "label": "事件", "evidence": "事件证据",
            }],
            formal_ending={"evidence": "终局证据"},
            expected_segment_count=1,
        )


def test_planning_compiler_rejects_alias_conflict_and_non_object_event() -> None:
    semantic = PlanningSemanticDraftV2.model_validate(_valid_semantic_payload())
    with pytest.raises(ValueError, match="aliases conflict"):
        compile_planning_semantic_v2(
            semantic,
            [{
                "id": "EV-00000001", "event_id": "EV-00000002",
                "label": "事件", "evidence": "事件证据",
            }],
            formal_ending={"evidence": "终局证据"},
            expected_segment_count=1,
        )
    with pytest.raises(ValueError, match="must be objects"):
        compile_planning_semantic_v2(
            semantic, [[("id", "EV-00000001")]],
            formal_ending={"evidence": "终局证据"},
            expected_segment_count=1,
        )
    compiled = compile_planning_semantic_v2(
        semantic,
        [{
            "id": "EV-00000001", "event_id": "EV-00000001",
            "label": "事件", "evidence": "事件证据",
        }],
        formal_ending={"evidence": "终局证据"},
        expected_segment_count=1,
    )
    assert compiled.document.segments[0].event_ids == ("EV-00000001",)


def test_formal_event_authority_uses_one_uppercase_identity_grammar() -> None:
    with pytest.raises(ValueError, match="invalid formal event IDs"):
        compile_planning_semantic_v2(
            PlanningSemanticDraftV2.model_validate(_valid_semantic_payload()),
            [{"id": "EV-0000000a", "label": "事件", "evidence": "事件证据"}],
            formal_ending={"evidence": "终局证据"},
            expected_segment_count=1,
        )
    with pytest.raises(PlanningGlobalClosureError):
        compute_planning_global_closure(
            [{
                "node_id": "EV-0000000a", "kind": "formal_event",
                "order": 1, "authority_sha256": SHA,
            }],
            [], ["EV-0000000a"],
        )
    contracts = narrative_outline_event_contracts(
        "### 发现线索\n\n主角发现了一项足以推进故事的关键线索。"
    )
    assert contracts
    assert all(item["id"] == item["id"].upper() for item in contracts)


def test_legacy_lowercase_formal_event_migrates_once_before_strict_closure() -> None:
    migrated = WorkflowService._planning_adaptation_contracts({}, [{
        "id": "EV-abcdef12", "order": 1, "label": "发现线索",
        "evidence": "主角发现了一项足以推进故事的关键线索。",
    }])
    assert migrated[0]["id"] == "EV-ABCDEF12"
    closure = build_runtime_planning_global_closure(migrated)
    assert closure["ordered_member_ids"] == ["EV-ABCDEF12"]


@pytest.mark.parametrize("invalid_id", ["EV-Abcd1234", " EV-abcdef12", True, 1])
def test_legacy_formal_event_migration_rejects_non_exact_shapes(invalid_id) -> None:
    with pytest.raises(ValueError):
        WorkflowService._canonical_formal_event_contracts([{
            "id": invalid_id, "order": 1, "label": "发现线索",
            "evidence": "主角发现了一项足以推进故事的关键线索。",
        }])


def test_legacy_formal_event_migration_rejects_alias_conflict_and_collision() -> None:
    with pytest.raises(ValueError, match="aliases conflict"):
        WorkflowService._canonical_formal_event_contracts([{
            "id": "EV-ABCDEF12", "event_id": "EV-abcdef12",
        }])
    with pytest.raises(ValueError, match="collides"):
        WorkflowService._canonical_formal_event_contracts([
            {"id": "EV-abcdef12"}, {"id": "EV-ABCDEF12"},
        ])


def test_planning_global_closure_is_transitive_cross_skill_and_order_independent() -> None:
    nodes = [
        {"node_id": "EV-00000003", "kind": "formal_event", "order": 3,
         "authority_sha256": "3" * 64},
        {"node_id": "SKILL-4444444444444444", "kind": "skill_source", "order": 0,
         "authority_sha256": "4" * 64},
        {"node_id": "EV-00000001", "kind": "formal_event", "order": 1,
         "authority_sha256": "1" * 64},
        {"node_id": "EV-00000002", "kind": "formal_event", "order": 2,
         "authority_sha256": "2" * 64},
    ]
    edges = [
        {"source": "EV-00000002", "target": "EV-00000003", "kind": "prerequisite"},
        {"source": "SKILL-4444444444444444", "target": "EV-00000001", "kind": "context"},
        {"source": "EV-00000001", "target": "EV-00000002", "kind": "prerequisite"},
    ]
    first = compute_planning_global_closure(nodes, edges, ["EV-00000003"])
    second = compute_planning_global_closure(
        list(reversed(nodes)), list(reversed(edges)), ["EV-00000003"],
    )
    assert first == second
    assert first["ordered_member_ids"] == [
        "SKILL-4444444444444444", "EV-00000001", "EV-00000002", "EV-00000003",
    ]


@pytest.mark.parametrize(
    ("edges", "code"),
    [
        ([{"source": "EV-00000001", "target": "MISSING", "kind": "prerequisite"}],
         "PLANNING_CLOSURE_MISSING_TARGET"),
        ([{"source": "EV-00000001", "target": "EV-00000002", "kind": "prerequisite"},
          {"source": "EV-00000002", "target": "EV-00000001", "kind": "prerequisite"}],
         "PLANNING_CLOSURE_CYCLE"),
        ([{"source": "EV-00000001", "target": "EV-00000002", "kind": "prerequisite"},
          {"source": "EV-00000001", "target": "EV-00000002", "kind": "prerequisite"}],
         "PLANNING_CLOSURE_DUPLICATE_EDGE"),
    ],
)
def test_planning_global_closure_fails_closed(
    edges: list[dict], code: str,
) -> None:
    nodes = [
        {"node_id": "EV-00000001", "kind": "formal_event", "order": 1,
         "authority_sha256": "1" * 64},
        {"node_id": "EV-00000002", "kind": "formal_event", "order": 2,
         "authority_sha256": "2" * 64},
    ]
    with pytest.raises(PlanningGlobalClosureError) as exc:
        compute_planning_global_closure(nodes, edges, ["EV-00000002"])
    assert exc.value.code == code


def test_planning_global_closure_rejects_non_string_identities() -> None:
    nodes = [{
        "node_id": 1, "kind": "formal_event", "order": 1,
        "authority_sha256": "1" * 64,
    }]
    with pytest.raises(PlanningGlobalClosureError):
        compute_planning_global_closure(nodes, [], ["1"])


def test_runtime_closure_rejects_conflicting_formal_event_id_aliases() -> None:
    with pytest.raises(PlanningGlobalClosureError) as exc:
        planning_closure_module.build_runtime_planning_global_closure([{
            "id": "EV-00000001",
            "event_id": "EV-00000002",
            "label": "conflict",
        }])
    assert exc.value.code == "PLANNING_CLOSURE_FORMAL_EVENT_ID_CONFLICT"


def test_planning_global_closure_rejects_disconnected_cycle() -> None:
    nodes = [
        {"node_id": "EV-00000001", "kind": "formal_event", "order": 1,
         "authority_sha256": "1" * 64},
        {"node_id": "EV-00000002", "kind": "formal_event", "order": 2,
         "authority_sha256": "2" * 64},
        {"node_id": "EV-00000003", "kind": "formal_event", "order": 3,
         "authority_sha256": "3" * 64},
    ]
    edges = [
        {"source": "EV-00000002", "target": "EV-00000003",
         "kind": "prerequisite"},
        {"source": "EV-00000003", "target": "EV-00000002",
         "kind": "prerequisite"},
    ]
    with pytest.raises(PlanningGlobalClosureError) as exc:
        compute_planning_global_closure(nodes, edges, ["EV-00000001"])
    assert exc.value.code == "PLANNING_CLOSURE_CYCLE"


def test_planning_global_closure_rejects_self_loop_as_cycle() -> None:
    nodes = [{
        "node_id": "EV-00000001", "kind": "formal_event", "order": 1,
        "authority_sha256": "1" * 64,
    }]
    with pytest.raises(PlanningGlobalClosureError) as exc:
        compute_planning_global_closure(nodes, [{
            "source": "EV-00000001", "target": "EV-00000001",
            "kind": "prerequisite",
        }], ["EV-00000001"])
    assert exc.value.code == "PLANNING_CLOSURE_CYCLE"


def test_planning_global_closure_exposes_and_enforces_resource_bounds() -> None:
    max_nodes = getattr(planning_closure_module, "MAX_NODE_COUNT", None)
    max_edges = getattr(planning_closure_module, "MAX_EDGE_COUNT", None)
    max_roots = getattr(planning_closure_module, "MAX_ROOT_COUNT", None)
    max_bytes = getattr(planning_closure_module, "MAX_SERIALIZED_BYTES", None)
    assert all(
        isinstance(value, int) and value > 0
        for value in (max_nodes, max_edges, max_roots, max_bytes)
    )
    nodes = [
        {
            "node_id": f"EV-{index:08X}", "kind": "formal_event",
            "order": index, "authority_sha256": f"{index % 16:x}" * 64,
        }
        for index in range(1, max_nodes + 2)
    ]
    with pytest.raises(PlanningGlobalClosureError) as exc:
        compute_planning_global_closure(nodes, [], ["EV-00000001"])
    assert exc.value.code == "PLANNING_CLOSURE_NODE_LIMIT_EXCEEDED"


@pytest.mark.parametrize(
    ("bound_name", "value", "code"),
    [
        ("MAX_EDGE_COUNT", 0, "PLANNING_CLOSURE_EDGE_LIMIT_EXCEEDED"),
        ("MAX_ROOT_COUNT", 0, "PLANNING_CLOSURE_ROOT_LIMIT_EXCEEDED"),
        ("MAX_SERIALIZED_BYTES", 1, "PLANNING_CLOSURE_SERIALIZED_BYTES_EXCEEDED"),
    ],
)
def test_planning_global_closure_each_resource_bound_fails_closed(
    monkeypatch, bound_name: str, value: int, code: str,
) -> None:
    monkeypatch.setattr(planning_closure_module, bound_name, value)
    nodes = [{
        "node_id": "EV-00000001", "kind": "formal_event", "order": 1,
        "authority_sha256": "1" * 64,
    }]
    edges = (
        [{
            "source": "EV-00000001", "target": "EV-00000001",
            "kind": "prerequisite",
        }]
        if bound_name == "MAX_EDGE_COUNT" else []
    )
    with pytest.raises(PlanningGlobalClosureError) as exc:
        compute_planning_global_closure(nodes, edges, ["EV-00000001"])
    assert exc.value.code == code


def test_sanitized_isomorphic_fixture_is_non_private_and_closed() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert fixture["classification"] == "synthetic_non_private"
    assert fixture["external_actions"] == 0
    assert fixture["draft"]["ambiguous_ownership"] == "fail_closed"
    assert fixture["style_reference"]["quality_reference_visibility"] == (
        "identity_only_manual_calibration"
    )


def _draft_finding(item: str, occurrences: int, identity: str) -> DraftRetryFindingV1:
    payload = {
        "schema": "DraftRetryFindingV1",
        "version": 1,
        "finding_code": "unapproved_mixed_script",
        "validator_reason_code": "reject_unapproved_mixed_script",
        "normalized_item": item,
        "authority_status": "unapproved",
        "validator_policy_sha256": SHA,
        "authority_snapshot_reference_sha256": "b" * 64,
        "validator_decision_binding_sha256": "c" * 64,
        "retry_scope_id": "segment-1",
    }
    computed_identity = hashlib.sha256(json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")).hexdigest()
    return DraftRetryFindingV1(
        schema="DraftRetryFindingV1",
        version=1,
        finding_code="unapproved_mixed_script",
        validator_reason_code="reject_unapproved_mixed_script",
        normalized_item=item,
        occurrence_count=occurrences,
        authority_status="unapproved",
        validator_policy_sha256=SHA,
        authority_snapshot_reference_sha256="b" * 64,
        validator_decision_binding_sha256="c" * 64,
        retry_scope_id="segment-1",
        finding_identity_sha256=computed_identity,
    )


def _draft_validator_authority() -> DraftProseAuthorityContextV1:
    source_sha256 = "d" * 64
    segment_sha256 = "e" * 64
    authority_sha256 = "f" * 64
    source = AuthorityTermSourceArtifactV1(
        artifact_kind="planning_segment_ir",
        artifact_sha256=source_sha256,
        contract="PlanningSegmentIR",
        version=1,
        authority_status="accepted_current",
    )
    term_set = build_authority_approved_latin_term_set(
        draft_authority_revision=1,
        draft_authority_sha256=authority_sha256,
        segment_binding_sha256=segment_sha256,
        source_artifacts=(source,),
        fields=(AuthorityTermProjectionFieldV1(
            source_artifact_sha256=source_sha256,
            field_path="segments/1/event_body",
            value="正式事件只允许ApprovedOnly术语",
            segment_binding_sha256=segment_sha256,
        ),),
    )
    return DraftProseAuthorityContextV1(
        term_set=term_set,
        current_draft_authority_revision=1,
        current_draft_authority_sha256=authority_sha256,
        current_segment_binding_sha256=segment_sha256,
        current_source_artifact_sha256s=(source_sha256,),
    )


def _draft_finding_batch(draft: str):
    decisions = analyze_prose(
        draft, authority_context=_draft_validator_authority(),
    )["mixed_script_decisions"]
    return build_draft_retry_findings(
        draft, decisions, retry_scope_id="segment-1",
    )


def test_draft_local_repair_preserves_all_unowned_bytes() -> None:
    draft = "第一段保持不变。\n\n第二段含有BadToken，需要局部修正。\n\n第三段也保持不变。"
    findings = _draft_finding_batch(draft)
    finding = findings[0]
    units = build_draft_local_repair_units(draft, findings)

    assert len(units) == 1
    assert units[0].finding_identity_sha256s == (
        finding.finding_identity_sha256,
    )
    repaired = apply_draft_local_repair_units(
        draft,
        [(units[0], "第二段含有异常词，需要局部修正。")],
    )
    assert repaired == "第一段保持不变。\n\n第二段含有异常词，需要局部修正。\n\n第三段也保持不变。"
    assert repaired[: units[0].start] == draft[: units[0].start]
    assert repaired.endswith("\n\n第三段也保持不变。")


def test_draft_multiple_local_defects_are_bounded_and_ambiguous_count_fails_closed() -> None:
    draft = "甲段有BadOne。\n\n乙段有BadTwo。\n\n丙段安全。"
    findings = _draft_finding_batch(draft)
    units = build_draft_local_repair_units(draft, findings)
    assert len(units) == 2
    assert [unit.start for unit in units] == sorted(unit.start for unit in units)
    repaired = apply_draft_local_repair_units(draft, [
        (units[0], "甲段有修正一。"),
        (units[1], "乙段有修正二。"),
    ])
    assert repaired == "甲段有修正一。\n\n乙段有修正二。\n\n丙段安全。"
    assert repaired.endswith("\n\n丙段安全。")
    with pytest.raises(DraftRetryFindingContractError):
        build_draft_local_repair_units(
            draft, [replace(findings[0], occurrence_count=2)],
        )


def test_draft_same_rejected_token_across_paragraphs_repairs_independently() -> None:
    draft = "甲段有BadToken。\n\n乙段也有BadToken。"
    findings = _draft_finding_batch(draft)
    units = build_draft_local_repair_units(draft, findings)
    assert len(units) == 2
    source_sha256 = hashlib.sha256(draft.encode("utf-8")).hexdigest()

    accepted = []
    for unit, replacement in zip(units, ("甲段已修正。", "乙段也已修正。")):
        payload = {
            "source_draft_sha256": source_sha256,
            "units": [{
                "unit_id": unit.unit_id,
                "source_unit_sha256": unit.source_unit_sha256,
                "finding_identity_sha256s": list(
                    unit.finding_identity_sha256s
                ),
                "replacement": replacement,
            }],
        }
        _candidate, replacements = normalize_draft_local_repair_contract(
            payload, draft, (unit,),
        )
        accepted.extend(replacements)

    candidate = apply_draft_local_repair_units(draft, accepted)
    assert candidate == "甲段已修正。\n\n乙段也已修正。"
    assert "BadToken" not in candidate


@pytest.mark.parametrize(
    "change",
    [
        {"version": True},
        {"occurrence_count": True},
    ],
)
def test_draft_local_repair_rejects_boolean_finding_scalars(change) -> None:
    draft = "甲段含BadToken。"
    batch = _draft_finding_batch(draft)
    finding = replace(batch[0], **change)
    with pytest.raises(DraftRetryFindingContractError):
        forged_batch = type(batch)(
            [finding], source_draft_sha256=batch.source_draft_sha256,
            _signature=batch._validator_signature,
        )
        build_draft_local_repair_units(draft, forged_batch)


@pytest.mark.parametrize(
    "change",
    [
        {"version": True},
        {"start": False},
        {"end": True},
    ],
)
def test_draft_local_repair_rejects_boolean_unit_scalars(change) -> None:
    draft = "甲段含BadToken。"
    unit = build_draft_local_repair_units(
        draft, _draft_finding_batch(draft),
    )[0]
    with pytest.raises(DraftRetryFindingContractError):
        apply_draft_local_repair_units(
            draft, [(replace(unit, **change), "甲段已修正。")],
        )


def test_forged_draft_finding_cannot_acquire_retry_or_repair_authority() -> None:
    draft = "甲段含BadToken。"
    batch = _draft_finding_batch(draft)
    original = batch[0]
    forged_binding = "9" * 64
    identity_payload = {
        "schema": original.schema,
        "version": original.version,
        "finding_code": original.finding_code,
        "validator_reason_code": original.validator_reason_code,
        "normalized_item": original.normalized_item,
        "authority_status": original.authority_status,
        "validator_policy_sha256": original.validator_policy_sha256,
        "authority_snapshot_reference_sha256": (
            original.authority_snapshot_reference_sha256
        ),
        "validator_decision_binding_sha256": forged_binding,
        "retry_scope_id": original.retry_scope_id,
    }
    forged = replace(
        original,
        validator_decision_binding_sha256=forged_binding,
        finding_identity_sha256=hashlib.sha256(json.dumps(
            identity_payload, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")).hexdigest(),
    )
    forged_batch = type(batch)(
        [forged], source_draft_sha256=batch.source_draft_sha256,
        _signature=batch._validator_signature,
    )
    with pytest.raises(
        DraftRetryFindingContractError,
        match="validator_finding_origin_unprovable",
    ):
        render_actionable_draft_validation_findings(forged_batch)
    with pytest.raises(
        DraftRetryFindingContractError,
        match="validator_finding_origin_unprovable",
    ):
        build_draft_local_repair_units(draft, forged_batch)


def test_draft_local_repair_replacement_rejects_new_blocking_finding() -> None:
    validate_draft_local_repair_replacement(
        "这一段只保留中文叙述。", authority_context=None,
    )
    with pytest.raises(
        DraftRetryFindingContractError,
        match="local_repair_replacement_introduced_finding",
    ):
        validate_draft_local_repair_replacement(
            "这一段却引入NewBad。", authority_context=None,
        )


def test_selected_style_reference_provenance_is_deterministic_and_claim_bounded(tmp_path) -> None:
    profile = "# 作品文风\n\n动作推动情绪，避免抽象总结。\n"
    profile_path = tmp_path / "style-profile.md"
    profile_path.write_text(profile, encoding="utf-8")
    actual_profile_bytes = profile_path.read_bytes()
    actual_profile_text = actual_profile_bytes.decode("utf-8")
    project = SimpleNamespace(
        id="project-1",
        path=tmp_path,
        metadata={
            "genre": "悬疑",
            "style_sample_scope": "draft_and_polish",
        },
    )
    group = {
        "id": "group-1",
        "version": 3,
        "items": [
            {
                "id": "reference:ref-1:v2",
                "role": "high_quality_anchor",
                "source_kind": "reference",
                "source_id": "ref-1",
                "version_id": "v2",
            }
        ],
    }
    first = selected_style_reference_provenance(project, group)
    second = selected_style_reference_provenance(project, group)
    assert first == second
    assert first["style_profile_sha256"] == hashlib.sha256(
        actual_profile_bytes,
    ).hexdigest()
    assert first["reference_evidence_status"] == "identity_only_not_model_visible"

    planning = render_selected_style_reference_context(first, stage="planning")
    final_review = render_selected_style_reference_context(first, stage="final_review")
    assert actual_profile_text not in planning
    assert actual_profile_text in final_review
    assert "UNSUPPORTED_FIDELITY_CLAIMS_FORBIDDEN" in final_review
    assert "exact imitation" in final_review
    assert "group-1" not in planning
    assert "reference:ref-1:v2" not in final_review
    receipt = final_review_style_reference_receipt(
        first, {"score": 100, "issues": [], "decision": "pass"},
        rendered_context_sha256="a" * 64,
        reviewed_input_sha256="b" * 64,
    )
    assert receipt["status"] == "selected_guidance_context_bound"
    assert receipt["supported_claim_type"] == "uses_selected_style_guidance"
    with pytest.raises(ValueError):
        final_review_style_reference_receipt(
            first, {"summary": "This is an exact imitation."},
        )


def test_style_reference_identity_set_orders_on_every_identity_field(tmp_path) -> None:
    project = SimpleNamespace(
        id="project-1", path=tmp_path,
        metadata={"genre": "悬疑", "style_sample_scope": "none"},
    )
    common = {
        "id": "same", "role": "same", "source_id": "same",
        "version_id": "same",
    }
    alpha = {**common, "source_kind": "alpha"}
    beta = {**common, "source_kind": "beta"}
    first = selected_style_reference_provenance(project, {
        "id": "group", "version": 1, "items": [beta, alpha],
    })
    second = selected_style_reference_provenance(project, {
        "id": "group", "version": 1, "items": [alpha, beta],
    })
    assert first == second
    assert [
        item["source_kind"] for item in first["quality_reference_identities"]
    ] == ["alpha", "beta"]

    corrupted = {
        key: value for key, value in first.items()
        if key not in {"authority_sha256", "style_profile_text"}
    }
    corrupted["quality_reference_identities"] = list(reversed(
        corrupted["quality_reference_identities"],
    ))
    corrupted["quality_reference_identity_set_sha256"] = hashlib.sha256(
        json.dumps(
            corrupted["quality_reference_identities"], ensure_ascii=False,
            sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8"),
    ).hexdigest()
    corrupted["authority_sha256"] = hashlib.sha256(json.dumps(
        corrupted, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")).hexdigest()
    with pytest.raises(ValueError, match="identity set"):
        style_context_module.validate_frozen_style_reference_authority(
            corrupted, corrupted,
        )


def test_style_authority_treats_absence_as_a_comparable_frozen_state(tmp_path) -> None:
    validator = getattr(
        style_context_module, "validate_frozen_style_reference_authority", None,
    )
    assert callable(validator)
    (tmp_path / "style-profile.md").write_text(
        "# 作品文风\n\n动作推动情绪。\n", encoding="utf-8",
    )
    selected_project = SimpleNamespace(
        id="project-1", path=tmp_path,
        metadata={"genre": "悬疑", "style_sample_scope": "draft_and_polish"},
    )
    none_project = SimpleNamespace(
        id="project-1", path=tmp_path,
        metadata={"genre": "悬疑", "style_sample_scope": "none"},
    )
    selected = selected_style_reference_provenance(selected_project, {})
    removed = selected_style_reference_provenance(none_project, {})
    with pytest.raises(ValueError):
        validator(selected, removed)
    assert validator(selected, selected)["authority_sha256"] == (
        selected["authority_sha256"]
    )
    assert validator(removed, removed)["selection_status"] == "not_requested"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("selection_status", "not_requested"),
        ("selection_scope", "unknown_scope"),
        ("style_profile_state", "unknown_state"),
        ("quality_reference_group_state", "unknown_state"),
        ("reference_evidence_status", "unknown_state"),
    ],
)
def test_style_authority_rejects_self_rehashed_semantic_state_corruption(
    tmp_path, field, value,
) -> None:
    (tmp_path / "style-profile.md").write_text(
        "# 作品文风\n\n动作推动情绪。\n", encoding="utf-8",
    )
    project = SimpleNamespace(
        id="project-1", path=tmp_path,
        metadata={"genre": "悬疑", "style_sample_scope": "draft_and_polish"},
    )
    frozen = selected_style_reference_provenance(project, {})
    corrupted = {
        key: value for key, value in frozen.items()
        if key not in {"authority_sha256", "style_profile_text"}
    }
    corrupted[field] = value
    corrupted["authority_sha256"] = hashlib.sha256(json.dumps(
        corrupted, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")).hexdigest()
    with pytest.raises(ValueError, match="style/reference"):
        style_context_module.validate_frozen_style_reference_authority(
            corrupted, corrupted,
        )
    with pytest.raises(ValueError, match="style/reference"):
        final_review_style_reference_receipt(
            corrupted,
            {"score": 100, "issues": [], "decision": "pass"},
        )


def test_style_authority_freezes_missing_profile_without_creating_it(tmp_path) -> None:
    project = SimpleNamespace(
        id="project-1", path=tmp_path,
        metadata={"genre": "悬疑", "style_sample_scope": "draft_and_polish"},
    )
    profile_path = tmp_path / "style-profile.md"
    frozen = selected_style_reference_provenance(project, {})
    assert frozen["selection_status"] == "selected"
    assert frozen["style_profile_state"] == "missing"
    assert frozen["style_profile_sha256"] == ""
    assert not profile_path.exists()
    assert style_context_module.validate_frozen_style_reference_authority(
        frozen, selected_style_reference_provenance(project, {}),
    )["style_profile_state"] == "missing"


def test_style_authority_binds_present_empty_profile_bytes(tmp_path) -> None:
    (tmp_path / "style-profile.md").write_bytes(b"")
    project = SimpleNamespace(
        id="project-1", path=tmp_path,
        metadata={"genre": "悬疑", "style_sample_scope": "draft_and_polish"},
    )
    frozen = selected_style_reference_provenance(project, {})
    assert frozen["style_profile_state"] == "present"
    assert frozen["style_profile_sha256"] == hashlib.sha256(b"").hexdigest()
    receipt = final_review_style_reference_receipt(
        frozen, {"score": 100, "issues": [], "decision": "pass"},
        rendered_context_sha256="a" * 64,
        reviewed_input_sha256="b" * 64,
    )
    assert receipt["status"] == "selected_guidance_context_bound"
    assert receipt["supported_claim_type"] == "uses_selected_style_guidance"
    assert receipt["claim"] is not None


def test_style_authority_binds_crlf_profile_actual_bytes(tmp_path) -> None:
    profile_bytes = b"# Style\r\n\r\nline\r\n"
    (tmp_path / "style-profile.md").write_bytes(profile_bytes)
    project = SimpleNamespace(
        id="project-1", path=tmp_path,
        metadata={"genre": "悬疑", "style_sample_scope": "draft_and_polish"},
    )
    frozen = selected_style_reference_provenance(project, {})
    assert frozen["style_profile_text"] == profile_bytes.decode("utf-8")
    assert frozen["style_profile_sha256"] == hashlib.sha256(
        profile_bytes,
    ).hexdigest()


@pytest.mark.parametrize("profile_bytes", [b"", b"# Style\r\nline\r\n"])
def test_style_render_rejects_tampered_in_memory_profile_text(
    tmp_path, profile_bytes,
) -> None:
    (tmp_path / "style-profile.md").write_bytes(profile_bytes)
    project = SimpleNamespace(
        id="project-1", path=tmp_path,
        metadata={"genre": "悬疑", "style_sample_scope": "draft_and_polish"},
    )
    frozen = selected_style_reference_provenance(project, {})
    tampered = {**frozen, "style_profile_text": "TAMPERED PROFILE"}
    with pytest.raises(ValueError, match="profile text binding is stale"):
        render_selected_style_reference_context(tampered, stage="final_review")


def test_style_render_rejects_visible_text_for_missing_profile(tmp_path) -> None:
    project = SimpleNamespace(
        id="project-1", path=tmp_path,
        metadata={"genre": "悬疑", "style_sample_scope": "draft_and_polish"},
    )
    frozen = selected_style_reference_provenance(project, {})
    assert frozen["style_profile_state"] == "missing"
    tampered = {**frozen, "style_profile_text": "TAMPERED PROFILE"}
    with pytest.raises(ValueError, match="unavailable profile"):
        render_selected_style_reference_context(tampered, stage="final_review")


def test_unreadable_style_profile_byte_identity_is_audit_only(tmp_path) -> None:
    profile_bytes = b"\xff\xfeinvalid-utf8"
    (tmp_path / "style-profile.md").write_bytes(profile_bytes)
    project = SimpleNamespace(
        id="project-1", path=tmp_path,
        metadata={"genre": "悬疑", "style_sample_scope": "draft_and_polish"},
    )
    frozen = selected_style_reference_provenance(project, {})
    assert frozen["style_profile_state"] == "unreadable"
    assert frozen["style_profile_sha256"] == hashlib.sha256(
        profile_bytes,
    ).hexdigest()
    assert frozen["style_profile_text"] == ""
    rendered = render_selected_style_reference_context(
        frozen, stage="final_review",
    )
    receipt = final_review_style_reference_receipt(
        frozen, {"score": 100, "issues": [], "decision": "pass"},
        rendered_context_sha256=hashlib.sha256(
            rendered.encode("utf-8"),
        ).hexdigest(),
        reviewed_input_sha256="b" * 64,
    )
    assert receipt["status"] == (
        "selected_profile_unavailable_no_fidelity_claim"
    )
    assert receipt["supported_claim_type"] == "none"
    assert receipt["provenance_supported_evidence"] == []
    assert receipt["claim"] is None


def test_style_authority_is_bound_to_exact_project_identity(tmp_path) -> None:
    first = SimpleNamespace(
        id="project-a", path=tmp_path,
        metadata={"genre": "悬疑", "style_sample_scope": "draft_and_polish"},
    )
    second = SimpleNamespace(
        id="project-b", path=tmp_path,
        metadata=dict(first.metadata),
    )
    frozen = selected_style_reference_provenance(first, {})
    current = selected_style_reference_provenance(second, {})
    assert frozen["project_binding_sha256"] != current["project_binding_sha256"]
    with pytest.raises(ValueError, match="authority changed"):
        style_context_module.validate_frozen_style_reference_authority(
            frozen, current,
        )


@pytest.mark.parametrize(
    "group",
    [
        {"id": "g", "version": True, "items": [{
            "id": "r", "role": "high_quality_anchor",
            "source_kind": "reference", "source_id": "s", "version_id": "v",
        }]},
        {"id": "g", "version": 1, "items": [{
            "id": "r", "role": "high_quality_anchor",
            "source_kind": "reference", "source_id": 123, "version_id": "v",
        }]},
        {"id": "g", "version": 1, "items": [True]},
        {"id": "g", "version": 1, "items": "not-a-list"},
    ],
)
def test_style_authority_rejects_malformed_quality_reference_identity(
    tmp_path, group,
) -> None:
    project = SimpleNamespace(
        id="project-1", path=tmp_path,
        metadata={"genre": "悬疑", "style_sample_scope": "none"},
    )
    with pytest.raises(ValueError):
        selected_style_reference_provenance(project, group)


def _style_context_receipt(authority: dict) -> dict:
    context = render_selected_style_reference_context(
        authority, stage="final_review",
    )
    receipt = {
        "schema": "StyleReferenceContextReceiptV1",
        "version": 1,
        "stage": "final_review",
        "visibility": "mandatory_current_contract",
        "selected_authority_sha256": authority["authority_sha256"],
        "style_profile_sha256": authority["style_profile_sha256"],
        "context_sha256": hashlib.sha256(context.encode("utf-8")).hexdigest(),
        "context_packet_sha256": "1" * 64,
        "model_system_sha256": "2" * 64,
        "model_input_sha256": "3" * 64,
        "advisory_shedding_occurred": False,
        "dispatch_binding_status": "exact",
        "contract_attempt_index": 2,
        "contract_attempt_route": "primary",
    }
    receipt["receipt_sha256"] = hashlib.sha256(json.dumps(
        receipt, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()
    return receipt


def test_style_context_receipt_validates_exact_accepted_attempt(tmp_path) -> None:
    (tmp_path / "style-profile.md").write_text(
        "# 作品文风\n\n动作推动情绪。\n", encoding="utf-8",
    )
    project = SimpleNamespace(
        id="project-1", path=tmp_path,
        metadata={"genre": "悬疑", "style_sample_scope": "draft_and_polish"},
    )
    authority = selected_style_reference_provenance(project, {})
    receipt = _style_context_receipt(authority)
    validated = validate_style_reference_context_receipt(
        receipt, frozen_authority=authority, stage="final_review",
        require_contract_attempt=True,
        expected_model_input_sha256="3" * 64,
        expected_model_system_sha256="2" * 64,
        expected_context_packet_sha256="1" * 64,
    )
    assert validated["model_input_sha256"] == "3" * 64


def test_style_context_receipt_validates_without_persisting_raw_profile(
    tmp_path,
) -> None:
    (tmp_path / "style-profile.md").write_text(
        "# 作品文风\n\n动作推动情绪。\n", encoding="utf-8",
    )
    project = SimpleNamespace(
        id="project-1", path=tmp_path,
        metadata={"genre": "悬疑", "style_sample_scope": "draft_and_polish"},
    )
    in_memory_authority = selected_style_reference_provenance(project, {})
    persisted_authority = {
        key: value for key, value in in_memory_authority.items()
        if key != "style_profile_text"
    }
    receipt = _style_context_receipt(in_memory_authority)

    validated = validate_style_reference_context_receipt(
        receipt, frozen_authority=persisted_authority,
        stage="final_review", require_contract_attempt=True,
    )

    assert "style_profile_text" not in persisted_authority
    assert validated["style_profile_sha256"] == persisted_authority[
        "style_profile_sha256"
    ]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema", "OtherReceipt"),
        ("version", True),
        ("stage", "draft"),
        ("selected_authority_sha256", "f" * 64),
        ("style_profile_sha256", "f" * 64),
        ("dispatch_binding_status", "pending"),
        ("contract_attempt_index", True),
        ("contract_attempt_route", "other"),
    ],
)
def test_style_context_receipt_rejects_rehashed_semantic_tamper(
    tmp_path, field: str, value: object,
) -> None:
    (tmp_path / "style-profile.md").write_text(
        "# 作品文风\n\n动作推动情绪。\n", encoding="utf-8",
    )
    project = SimpleNamespace(
        id="project-1", path=tmp_path,
        metadata={"genre": "悬疑", "style_sample_scope": "draft_and_polish"},
    )
    authority = selected_style_reference_provenance(project, {})
    receipt = _style_context_receipt(authority)
    receipt[field] = value
    receipt.pop("receipt_sha256")
    receipt["receipt_sha256"] = hashlib.sha256(json.dumps(
        receipt, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()
    with pytest.raises(ValueError):
        validate_style_reference_context_receipt(
            receipt, frozen_authority=authority, stage="final_review",
            require_contract_attempt=True,
        )


def test_style_context_receipt_rejects_stale_self_hash(tmp_path) -> None:
    (tmp_path / "style-profile.md").write_text(
        "# 作品文风\n\n动作推动情绪。\n", encoding="utf-8",
    )
    project = SimpleNamespace(
        id="project-1", path=tmp_path,
        metadata={"genre": "悬疑", "style_sample_scope": "draft_and_polish"},
    )
    authority = selected_style_reference_provenance(project, {})
    receipt = _style_context_receipt(authority)
    receipt["model_input_sha256"] = "4" * 64
    with pytest.raises(ValueError, match="identity is invalid"):
        validate_style_reference_context_receipt(
            receipt, frozen_authority=authority, stage="final_review",
            require_contract_attempt=True,
        )


def test_style_context_receipt_cross_rejects_rehashed_dispatch_hash(tmp_path) -> None:
    (tmp_path / "style-profile.md").write_text(
        "# 作品文风\n\n动作推动情绪。\n", encoding="utf-8",
    )
    project = SimpleNamespace(
        id="project-1", path=tmp_path,
        metadata={"genre": "悬疑", "style_sample_scope": "draft_and_polish"},
    )
    authority = selected_style_reference_provenance(project, {})
    receipt = _style_context_receipt(authority)
    receipt["model_system_sha256"] = "4" * 64
    receipt.pop("receipt_sha256")
    receipt["receipt_sha256"] = hashlib.sha256(json.dumps(
        receipt, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()
    with pytest.raises(ValueError, match="model system binding is stale"):
        validate_style_reference_context_receipt(
            receipt, frozen_authority=authority, stage="final_review",
            require_contract_attempt=True,
            expected_model_input_sha256="3" * 64,
            expected_model_system_sha256="2" * 64,
            expected_context_packet_sha256="1" * 64,
        )


@pytest.mark.parametrize(
    "claim",
    [
        "The manuscript faithfully replicates the selected author voice.",
        "Its voice is indistinguishable from the reference author.",
        "文本忠实复刻了所选作者的全部文风。",
        "The result is perfectly equivalent to the writer's style.",
        "Its prose could have come from the same pen as the reference.",
        "This reads as though the reference writer wrote it.",
        "像是原作者亲笔写成。",
        "The prose captures every nuance of the selected novelist manner.",
        "The selected writer's manner is preserved without loss.",
        "The prose mirrors its exemplar in every respect.",
        "The prose could have been lifted wholesale from its source.",
        (
            "A reader could not tell this manuscript apart from the work that "
            "supplied the calibration benchmark."
        ),
        "行文完整保留了所选作家的全部神韵。",
    ],
)
def test_style_fidelity_contract_rejects_paraphrased_replication_claims(
    tmp_path, claim: str,
) -> None:
    (tmp_path / "style-profile.md").write_text(
        "# 作品文风\n\n动作推动情绪。\n", encoding="utf-8",
    )
    project = SimpleNamespace(
        id="project-1", path=tmp_path,
        metadata={"genre": "悬疑", "style_sample_scope": "draft_and_polish"},
    )
    provenance = selected_style_reference_provenance(project, {})
    with pytest.raises(ValueError):
        final_review_style_reference_receipt(
            provenance, {
                "score": 50,
                "issues": [{
                    "category": "style", "severity": "high",
                    "evidence": claim, "action": "Revise the prose.",
                }],
            },
        )


def test_style_fidelity_overclaim_fails_without_selected_provenance(tmp_path) -> None:
    project = SimpleNamespace(
        id="project-1", path=tmp_path,
        metadata={"genre": "悬疑", "style_sample_scope": "none"},
    )
    provenance = selected_style_reference_provenance(project, {})
    with pytest.raises(ValueError, match="unsupported style/reference"):
        final_review_style_reference_receipt(
            provenance,
            {
                "score": 50,
                "issues": [{
                    "category": "style", "severity": "high",
                    "evidence": (
                        "The prose faithfully replicates the selected author voice."
                    ),
                    "action": "Revise the prose.",
                }],
            },
        )


@pytest.mark.parametrize("scope", ["none", "draft_and_polish"])
def test_style_fidelity_contract_scans_typed_mapping_keys(
    tmp_path, scope: str,
) -> None:
    if scope == "draft_and_polish":
        (tmp_path / "style-profile.md").write_text(
            "# 作品文风\n\n动作推动情绪。\n", encoding="utf-8",
        )
    project = SimpleNamespace(
        id="project-1", path=tmp_path,
        metadata={"genre": "悬疑", "style_sample_scope": scope},
    )
    provenance = selected_style_reference_provenance(project, {})
    criterion = "Indistinguishable from the selected reference author voice"
    with pytest.raises(ValueError, match="unsupported style/reference"):
        final_review_style_reference_receipt(
            provenance,
            {
                "criteria": {criterion: 100},
                "criterion_evidence": {criterion: {
                    "location": "whole", "excerpt": "ordinary text",
                    "effect": "ordinary effect",
                }},
                "issues": [], "decision": "pass",
            },
            rendered_context_sha256="a" * 64,
            reviewed_input_sha256="b" * 64,
        )


@pytest.mark.parametrize("scope", ["none", "draft_and_polish"])
def test_style_fidelity_contract_combines_typed_mapping_key_and_value_semantics(
    tmp_path, scope: str,
) -> None:
    if scope == "draft_and_polish":
        (tmp_path / "style-profile.md").write_text(
            "# 作品文风\n\n动作推动情绪。\n", encoding="utf-8",
        )
    project = SimpleNamespace(
        id="project-1", path=tmp_path,
        metadata={"genre": "悬疑", "style_sample_scope": scope},
    )
    provenance = selected_style_reference_provenance(project, {})
    criterion = "Selected author"
    with pytest.raises(ValueError, match="unsupported style/reference"):
        final_review_style_reference_receipt(
            provenance,
            {
                "criteria": {criterion: 100},
                "criterion_evidence": {criterion: {
                    "location": "whole", "excerpt": "The prose throughout.",
                    "effect": "Indistinguishable.",
                }},
                "issues": [], "decision": "pass",
            },
            rendered_context_sha256="a" * 64,
            reviewed_input_sha256="b" * 64,
        )


@pytest.mark.parametrize(
    ("evidence", "action"),
    [
        ("Selected author", "Indistinguishable."),
        ("The source material", "Wholesale derivation."),
    ],
)
def test_style_fidelity_contract_combines_sibling_issue_semantics(
    tmp_path, evidence, action,
) -> None:
    project = SimpleNamespace(
        id="project-1", path=tmp_path,
        metadata={"genre": "悬疑", "style_sample_scope": "none"},
    )
    provenance = selected_style_reference_provenance(project, {})
    with pytest.raises(ValueError, match="unsupported style/reference"):
        final_review_style_reference_receipt(
            provenance,
            {
                "score": 80,
                "issues": [{
                    "category": "prose", "severity": "low",
                    "evidence": evidence, "action": action,
                }],
                "decision": "revise",
            },
        )


def test_style_fidelity_sibling_scan_does_not_cross_large_issue_collection(
    tmp_path,
) -> None:
    project = SimpleNamespace(
        id="project-1", path=tmp_path,
        metadata={"genre": "悬疑", "style_sample_scope": "none"},
    )
    provenance = selected_style_reference_provenance(project, {})
    receipt = final_review_style_reference_receipt(
        provenance,
        {
            "score": 80,
            "issues": [{
                "category": "prose", "severity": "low",
                "evidence": f"Paragraph {index} repeats a local transition.",
                "action": f"Revise paragraph {index} locally.",
            } for index in range(256)],
            "decision": "revise",
        },
    )
    assert receipt["status"] == "not_requested"


def test_style_fidelity_contract_emits_typed_evidence_bounded_claim(tmp_path) -> None:
    (tmp_path / "style-profile.md").write_text(
        "# 作品文风\n\n动作推动情绪。\n", encoding="utf-8",
    )
    project = SimpleNamespace(
        id="project-1", path=tmp_path,
        metadata={"genre": "悬疑", "style_sample_scope": "draft_and_polish"},
    )
    provenance = selected_style_reference_provenance(project, {})
    receipt = final_review_style_reference_receipt(
        provenance, {"score": 100, "issues": [], "decision": "pass"},
        rendered_context_sha256="a" * 64,
        reviewed_input_sha256="b" * 64,
    )
    claim = receipt.get("claim")
    assert claim == {
        "schema": "StyleReferenceFidelityClaimV1",
        "version": 1,
        "claim_category": "uses_selected_style_guidance",
        "claim_scope": "final_review_context",
        "evidence_sha256s": [
            provenance["authority_sha256"],
            provenance["style_profile_sha256"],
            "a" * 64,
            "b" * 64,
        ],
    }
    assert receipt["model_free_text_claim_authority"] == "none"

    invalid_claim = {**claim, "version": True}
    with pytest.raises(ValueError, match="exceeds Runtime evidence"):
        final_review_style_reference_receipt(
            provenance, {"score": 100, "issues": [], "decision": "pass"},
            rendered_context_sha256="a" * 64,
            reviewed_input_sha256="b" * 64,
            claim=invalid_claim,
        )


def test_style_fidelity_contract_allows_ordinary_prose_defect_without_reference(
    tmp_path,
) -> None:
    project = SimpleNamespace(
        id="project-1", path=tmp_path,
        metadata={"genre": "悬疑", "style_sample_scope": "none"},
    )
    provenance = selected_style_reference_provenance(project, {})
    receipt = final_review_style_reference_receipt(
        provenance,
        {
            "score": 80,
            "issues": [{
                "category": "prose", "severity": "low",
                "evidence": "This work has uneven prose in the middle.",
                "action": "Tighten the middle.",
            }],
            "decision": "revise",
        },
    )
    assert receipt["status"] == "not_requested"

    original_prose_receipt = final_review_style_reference_receipt(
        provenance,
        {
            "score": 80,
            "issues": [{
                "category": "prose", "severity": "low",
                "evidence": "The original prose repeats the same transition.",
                "action": "Tighten the transition.",
            }],
            "decision": "revise",
        },
    )
    assert original_prose_receipt["status"] == "not_requested"

    source_rewrite_receipt = final_review_style_reference_receipt(
        provenance,
        {
            "score": 80,
            "issues": [{
                "category": "prose", "severity": "low",
                "evidence": "The source draft's opening is repetitive.",
                "action": "Rewrite the opening wholesale.",
            }],
            "decision": "revise",
        },
    )
    assert source_rewrite_receipt["status"] == "not_requested"


@pytest.mark.parametrize(
    "evidence",
    [
        "The author wrote this chapter with too many passive constructions.",
        "The writer authored an ending that resolves the central promise too early.",
        "作者写成的结尾过早揭示了真相。",
        "The author wrote the opening in a terse style, but the middle is uneven.",
    ],
)
def test_style_fidelity_contract_allows_ordinary_authorship_critique(
    tmp_path, evidence,
) -> None:
    project = SimpleNamespace(
        id="project-1", path=tmp_path,
        metadata={"genre": "悬疑", "style_sample_scope": "none"},
    )
    provenance = selected_style_reference_provenance(project, {})
    receipt = final_review_style_reference_receipt(
        provenance,
        {
            "score": 80,
            "issues": [{
                "category": "prose", "severity": "low",
                "evidence": evidence, "action": "Revise this local issue.",
            }],
            "decision": "revise",
        },
    )
    assert receipt["status"] == "not_requested"
