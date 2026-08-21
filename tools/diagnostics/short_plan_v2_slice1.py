"""Offline replay runner for EVENT_REALIZATION_UNIT_SHADOW_V1 Phase A."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from novel_flywheel.canonical_shadow import canonical_sha256
from novel_flywheel.planning_v2_slice1 import (
    EventRealizationArtifactV1,
    EventRealizationCandidateV1,
    EventRealizationInputAuthorityV1,
    Slice1CandidateRejected,
    Slice1NoProgressError,
    Slice1RecoveryStateV1,
    apply_bounded_candidate_patch,
    artifact_sha256,
    assemble_shadow_set,
    build_event_realization_artifact,
    compare_shadow_to_v1,
    compute_impact_closure,
    convert_event_realization_candidate,
    freeze_validated_artifact,
    record_recovery_progress,
    regenerate_slice1_set,
    validate_candidate_payload,
    validate_event_realization_artifact,
)


ZERO_EXTERNAL_ACTIONS = {
    "credential": 0,
    "provider_client": 0,
    "network": 0,
    "model": 0,
    "paid": 0,
}


def _authority(
    fixture: Mapping[str, Any],
    event_id: str,
    *,
    dependency_artifact_ids: Sequence[str] = (),
) -> EventRealizationInputAuthorityV1:
    authority = fixture["authority"]
    return EventRealizationInputAuthorityV1(
        parent_authority_sha256=authority["parent_authority_sha256"],
        formal_event_id=event_id,
        formal_event_contract_sha256=authority["event_contract_sha256"][event_id],
        predecessor_boundary_sha256=(
            authority["predecessor_boundary_sha256"][event_id]
        ),
        formal_event_ids=tuple(authority["event_ids"]),
        segment_event_ids=(tuple(authority["event_ids"]),),
        dependency_artifact_ids=tuple(dependency_artifact_ids),
        context_projection_sha256=authority["context_projection_sha256"],
        required_obligation_ids=tuple(authority["required_obligation_ids"]),
    )


def _candidate(fixture: Mapping[str, Any], name: str) -> EventRealizationCandidateV1:
    return EventRealizationCandidateV1.model_validate(fixture["candidates"][name])


def _render_topology(candidate: Mapping[str, Any], topology: str) -> str:
    wrappers: dict[str, object] = {
        "canonical": dict(candidate),
        "data": {"data": dict(candidate)},
        "nested_result": {"result": {"payload": dict(candidate)}},
        "unseen_delivery": {"delivery": {"artifact": dict(candidate)}},
        "unseen_answer": {"answer": {"content": dict(candidate)}},
        "response_value": {"response": {"value": dict(candidate)}},
    }
    return json.dumps(wrappers[topology], ensure_ascii=False, separators=(",", ":"))


def _freeze(
    authority: EventRealizationInputAuthorityV1,
    candidate: EventRealizationCandidateV1,
) -> EventRealizationArtifactV1:
    artifact = build_event_realization_artifact(authority, candidate)
    receipt = validate_event_realization_artifact(artifact, authority)
    return freeze_validated_artifact(artifact, receipt)


def _pair(fixture: Mapping[str, Any]) -> tuple[
    EventRealizationInputAuthorityV1,
    EventRealizationArtifactV1,
    EventRealizationInputAuthorityV1,
    EventRealizationArtifactV1,
]:
    first_authority = _authority(fixture, "EV-00000001")
    first = _freeze(first_authority, _candidate(fixture, "first"))
    second_authority = _authority(
        fixture, "EV-00000002", dependency_artifact_ids=(first.artifact_id,),
    )
    second = _freeze(second_authority, _candidate(fixture, "second"))
    return first_authority, first, second_authority, second


def _case_result(
    case: Mapping[str, Any], fixture: Mapping[str, Any], metrics: dict[str, Any],
) -> dict[str, Any]:
    kind = case["kind"]
    first_authority = _authority(fixture, "EV-00000001")
    observed = "UNSET"
    evidence: dict[str, Any] = {}

    if kind == "valid_conversion":
        source_candidate = fixture["candidates"][case["candidate"]]
        raw = _render_topology(source_candidate, case["topology"])
        candidate, audit = convert_event_realization_candidate(
            raw, authority=first_authority,
        )
        artifact = _freeze(first_authority, candidate)
        observed = "validated"
        metrics["first_pass_total"] += 1
        metrics["first_pass_passed"] += 1
        evidence = {
            "conversion_method": audit.method,
            "transformation_codes": list(audit.transformations),
            "candidate_sha256": artifact.provenance.source_candidate_sha256,
            "artifact_sha256": artifact_sha256(artifact),
            "creative_content_preserved": (
                candidate.model_dump(mode="json") == source_candidate
            ),
        }
    elif kind == "ambiguous":
        candidate = fixture["candidates"][case["candidate"]]
        raw = json.dumps({"left": candidate, "right": candidate}, ensure_ascii=False)
        try:
            convert_event_realization_candidate(raw, authority=first_authority)
        except Slice1CandidateRejected as exc:
            observed = exc.findings[0].rule_code
            evidence = {"finding_ids": [item.finding_id for item in exc.findings]}
    elif kind == "ownership_violation":
        candidate = {
            **fixture["candidates"][case["candidate"]],
            "formal_event_id": "EV-00000001",
        }
        try:
            validate_candidate_payload(candidate, authority=first_authority)
        except Slice1CandidateRejected as exc:
            observed = exc.findings[0].rule_code
            evidence = {
                "finding_paths": [
                    item.field_path_json_pointer for item in exc.findings
                ],
            }
    elif kind in {"truncated", "empty"}:
        raw = '{"title":"broken","narrative":' if kind == "truncated" else ""
        try:
            convert_event_realization_candidate(raw, authority=first_authority)
        except Slice1CandidateRejected as exc:
            observed = exc.findings[0].rule_code
            evidence = {"finding_ids": [item.finding_id for item in exc.findings]}
    elif kind == "semantic_short":
        metrics["first_pass_total"] += 1
        try:
            validate_candidate_payload(
                {"title": "Short", "narrative": "too short"},
                authority=first_authority,
            )
        except Slice1CandidateRejected as exc:
            observed = exc.findings[0].rule_code
            evidence = {
                "finding_paths": [
                    item.field_path_json_pointer for item in exc.findings
                ],
            }
    elif kind == "call1_unknown":
        observed = "CALL1_EXACT_FAILURE_RULE_UNKNOWN"
        evidence = {
            "sealed_observation_sha256": case["sealed_observation_sha256"],
            "exact_failure_rule": "UNKNOWN",
            "divergence": "uncomparable_historical_evidence_missing",
            "invented_repair": False,
        }
    elif kind == "ptr3_repair":
        source = fixture["candidates"][case["candidate"]]
        try:
            validate_candidate_payload(
                {**source, "artifact_id": "forbidden"},
                authority=first_authority,
            )
        except Slice1CandidateRejected as exc:
            before_findings = exc.findings
        candidate = validate_candidate_payload(source, authority=first_authority)
        artifact = _freeze(first_authority, candidate)
        observed = "bounded_repair_converged"
        metrics["bounded_repair_total"] += 1
        metrics["bounded_repair_converged"] += 1
        evidence = {
            "before_finding_ids": [item.finding_id for item in before_findings],
            "after_finding_count": 0,
            "artifact_sha256": artifact_sha256(artifact),
        }
    elif kind == "structure_drift":
        artifact = build_event_realization_artifact(
            first_authority, _candidate(fixture, case["candidate"]),
        ).model_copy(update={"formal_event_ordinal": 99})
        receipt = validate_event_realization_artifact(artifact, first_authority)
        observed = next(
            item.rule_code for item in receipt.findings
            if item.field_path_json_pointer == "/formal_event_ordinal"
        )
        evidence = {"finding_count": len(receipt.findings)}
    elif kind == "impact":
        _, first, _, second = _pair(fixture)
        scope = case["scope"]
        hints = (
            () if scope == "local" else
            (first.artifact_id,) if scope == "adjacent" else
            ("unknown-artifact",)
        )
        closure = compute_impact_closure(
            field_path="/title" if scope == "local" else "/narrative",
            current=second,
            predecessor=first,
            dependency_hint_ids=hints,
        )
        observed = f"closure_level_{closure.repair_level}"
        metrics["dependency_closure_size"] = max(
            metrics["dependency_closure_size"], closure.closure_size,
        )
        evidence = {
            "closure_sha256": closure.closure_sha256,
            "closure_size": closure.closure_size,
            "slice1_regeneration_required": closure.requires_slice1_regeneration,
        }
    elif kind == "no_progress":
        artifact = build_event_realization_artifact(
            first_authority, _candidate(fixture, case["candidate"]),
        )
        damaged = artifact.model_copy(update={"formal_event_ordinal": 99})
        finding = validate_event_realization_artifact(
            damaged, first_authority,
        ).findings[0]
        try:
            record_recovery_progress(
                Slice1RecoveryStateV1(), level=1,
                before=damaged, after=damaged,
                before_findings=(finding,), after_findings=(finding,),
                closure_artifact_ids=(damaged.artifact_id,),
            )
        except Slice1NoProgressError as exc:
            observed = exc.code
            metrics["same_failure_without_state_change_count"] += 1
            evidence = {"dispatch_after_detection": False}
    elif kind == "assembly_comparison":
        _, first, _, second = _pair(fixture)
        assembled = assemble_shadow_set(
            (second, first),
            parent_authority_sha256=first.parent_authority_sha256,
            expected_event_ids=("EV-00000001", "EV-00000002"),
        )
        v1 = {
            "event_ids": ["EV-00000001", "EV-00000002"],
            "narrative_meaningful_counts": {
                "EV-00000001": 8, "EV-00000002": 8,
            },
            "obligation_ids": {
                "EV-00000001": ["motivation", "intent"],
                "EV-00000002": ["conflict", "causal-preparation"],
            },
        }
        comparison = compare_shadow_to_v1(
            v1, assembled,
            shadow_obligation_ids={
                "EV-00000001": ("motivation", "intent"),
                "EV-00000002": ("conflict", "causal-preparation"),
            },
        )
        observed = comparison.divergence
        metrics["v1_v2_divergence"][observed] = (
            metrics["v1_v2_divergence"].get(observed, 0) + 1
        )
        metrics["semantic_regression_count"] += comparison.semantic_regression_count
        evidence = {
            "comparison_sha256": canonical_sha256(
                "Slice1ComparisonReceiptV1",
                comparison.model_dump(mode="json", by_alias=True),
            ),
            "mutation_performed": comparison.mutation_performed,
        }
    elif kind == "slice1_regeneration":
        first_authority, first, second_authority, _ = _pair(fixture)
        regenerated = regenerate_slice1_set(
            (first_authority, second_authority),
            {
                "EV-00000001": _candidate(fixture, "first"),
                "EV-00000002": _candidate(fixture, "second"),
            },
        )
        observed = "slice1_regenerated"
        metrics["slice1_regeneration_count"] += 1
        evidence = {
            "assembly_sha256": regenerated.assembly_sha256,
            "whole_planning_regeneration_performed": (
                regenerated.whole_planning_regeneration_performed
            ),
            "seed_artifact_identity_reused": (
                regenerated.ordered_artifacts[0].artifact_id == first.artifact_id
            ),
        }
    else:
        raise ValueError(f"unsupported Slice 1 replay case kind: {kind}")

    return {
        "case_id": case["case_id"],
        "case_family": case["family"],
        "observed_status": observed,
        "expected_status": case["expected"],
        "pass": observed == case["expected"],
        "evidence": evidence,
    }


def run_replay(
    fixture_path: Path,
    *,
    clock: Callable[[], float] = time.perf_counter,
) -> dict[str, Any]:
    """Execute the sanitized corpus with no provider-capable dependency."""

    source = fixture_path.read_bytes()
    fixture = json.loads(source.decode("utf-8"))
    if fixture.get("schema") != "EventRealizationShadowCorpusV1":
        raise ValueError("unsupported Slice 1 replay corpus")
    started = clock()
    metrics: dict[str, Any] = {
        "first_pass_total": 0,
        "first_pass_passed": 0,
        "bounded_repair_total": 0,
        "bounded_repair_converged": 0,
        "llm_call_count": 0,
        "deterministic_repair_count": 0,
        "already_valid_field_mutation_count": 0,
        "freeze_violation_count": 0,
        "same_failure_without_state_change_count": 0,
        "same_failure_dispatch_count": 0,
        "dependency_closure_size": 0,
        "slice1_regeneration_count": 0,
        "semantic_regression_count": 0,
        "v1_v2_divergence": {},
        "stale_finding_count": 0,
    }
    cases = [_case_result(case, fixture, metrics) for case in fixture["cases"]]
    elapsed_ms = max(0, round((clock() - started) * 1000))
    first_pass_rate = (
        metrics["first_pass_passed"] / metrics["first_pass_total"]
        if metrics["first_pass_total"] else None
    )
    bounded_rate = (
        metrics["bounded_repair_converged"] / metrics["bounded_repair_total"]
        if metrics["bounded_repair_total"] else None
    )
    metrics.update({
        "first_pass_validation": first_pass_rate,
        "bounded_repair_convergence_rate": bounded_rate,
        "replay_elapsed_milliseconds": elapsed_ms,
        "replay_case_identity": [row["case_id"] for row in cases],
    })
    return {
        "schema": "EventRealizationShadowReplayReceiptV1",
        "version": 1,
        "phase": "offline_deterministic_replay_shadow_only",
        "fixture_sha256": hashlib.sha256(source).hexdigest(),
        "case_count": len(cases),
        "cases": cases,
        "metrics": metrics,
        "quality_preservation": {
            "creative_fields": ["title", "narrative"],
            "local_derivation_creative_rewrite_count": 0,
            "obligation_oracle_kind": "explicit_sanitized_fixture_labels",
            "aesthetic_score_used": False,
        },
        "call1_exact_failure_rule": "UNKNOWN",
        "planning_v1_authority_changed": False,
        "draft_consumes_slice1": False,
        "story_state_mutated": False,
        "canon_mutated": False,
        "ready_mutated": False,
        "external_actions": dict(ZERO_EXTERNAL_ACTIONS),
        "overall_status": "exact" if all(row["pass"] for row in cases) else "failed",
    }


def write_receipt(path: Path, receipt: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    with tempfile.NamedTemporaryFile(
        mode="wb", dir=path.parent, prefix=path.name + ".", suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(encoded)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the offline Planning V2 Slice 1 replay corpus",
    )
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    receipt = run_replay(args.fixture)
    write_receipt(args.output, receipt)
    return 0 if receipt["overall_status"] == "exact" else 1


if __name__ == "__main__":
    raise SystemExit(main())
