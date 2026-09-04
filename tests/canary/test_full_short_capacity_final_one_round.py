from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(
    "docs/superpowers/reports/"
    "full-short-capacity-final-one-round-confirmation-v1"
)
REQUIRED = {
    "README.md",
    "baseline-binding-v1.json",
    "agent-a-segmentation-windowing-v1.json",
    "agent-b-physical-input-envelope-v1.json",
    "agent-c-output-cap-lineage-v1.json",
    "agent-d-workload-sufficiency-v1.json",
    "agent-e-lingsuan-provenance-v1.json",
    "agent-f-final-capacity-review-v1.json",
    "segmentation-windowing-boundary-matrix-v1.json",
    "exact-ready-physical-input-envelope-v1.json",
    "output-cap-lineage-matrix-v1.json",
    "planning-8328-classification-v1.json",
    "lingsuan-historical-provenance-v1.json",
    "exact-ready-authoritative-physical-attempt-matrix-v1.json",
    "route-workload-admission-v1.json",
    "capacity-final-stop-loss-v1.json",
    "sha256-manifest-v1.json",
}
ZERO_BOUNDARY = {
    "real_credential_lookup_count": 0,
    "real_secret_read_count": 0,
    "real_provider_client_creation_count": 0,
    "real_provider_request_attempts": 0,
    "http_post_attempts": 0,
    "network_model_api_calls": 0,
    "model_calls": 0,
    "paid_calls": 0,
    "full_short_real_execution_count": 0,
}


def _load(name: str) -> dict[str, object]:
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def test_final_capacity_evidence_is_complete_and_self_consistent() -> None:
    assert REQUIRED <= {path.name for path in ROOT.iterdir() if path.is_file()}

    envelope = _load("exact-ready-physical-input-envelope-v1.json")
    matrix = _load("exact-ready-authoritative-physical-attempt-matrix-v1.json")
    stop = _load("capacity-final-stop-loss-v1.json")
    lineage = _load("output-cap-lineage-matrix-v1.json")
    planning = _load("planning-8328-classification-v1.json")

    assert envelope["exact_ready_physical_attempt_envelope_complete"] is True
    assert envelope["unsealed_required_stage_input_count"] == 0
    assert envelope["unsealed_required_attempt_output_cap_count"] == 0
    assert matrix["exact_ready_total_physical_attempt_shapes"] == 183
    assert matrix["exact_ready_proven_safe_physical_attempt_shapes"] == 72
    assert matrix["exact_ready_unproven_physical_attempt_count"] == 111
    assert len(matrix["attempts"]) == 183
    assert len(stop["blocked_attempts"]) == 111
    assert (
        matrix["exact_ready_proven_safe_physical_attempt_shapes"]
        + matrix["exact_ready_unproven_physical_attempt_count"]
        == matrix["exact_ready_total_physical_attempt_shapes"]
    )
    assert planning["planning_8328_classification"] == "WIRE_REQUESTED_CAP"
    assert planning["planning_physical_attempt_max_requested_output"] == 8328
    assert lineage["output_cap_conflation_bug_count"] == 0
    assert all(
        attempt["physical_attempt_requested_output_cap"]
        == attempt["provider_wire_requested_output_cap"]
        for attempt in lineage["attempts"]
    )
    assert stop["full_short_production_shaped_dry_run"] == "NOT_RUN_STOP_LOSS"
    assert stop["final_authorization_ready"] is False
    assert stop["exact_next_gate"] == (
        "FULL_SHORT_MINIMAL_REMAINING_ROUTE_EVIDENCE_OR_ROUTE_DECISION_REQUIRED"
    )


def test_admission_is_route_bound_without_guessed_maxima_or_raw_prompts() -> None:
    matrix = _load("exact-ready-authoritative-physical-attempt-matrix-v1.json")
    admission = _load("route-workload-admission-v1.json")
    segmentation = _load("segmentation-windowing-boundary-matrix-v1.json")

    assert admission["route_with_guessed_capability_count"] == 0
    assert admission["required_route_max_context_unknown_count"] == 5
    assert admission["required_route_max_output_unknown_count"] == 5
    assert len(admission["route_records"]) == 7
    assert segmentation["unbounded_physical_request_path_count"] == 0
    assert segmentation[
        "manuscript_length_used_as_direct_route_capacity_blocker_count"
    ] == 0
    assert all(attempt["raw_prompt_persisted"] is False for attempt in matrix["attempts"])
    assert all(attempt["route_fingerprint"] for attempt in matrix["attempts"])
    assert all(attempt["input_envelope_sha256"] for attempt in matrix["attempts"])
    assert all(
        attempt["evidence_source_sha256"] for attempt in matrix["attempts"]
    )
    for attempt in matrix["attempts"]:
        assert attempt["admission_result"] in {"PASS", "BLOCKED"}
        if attempt["admission_result"] == "BLOCKED":
            assert attempt["stage"]
            assert attempt["attempt_role"]
            assert attempt["current_input_requirement"] is not None
            assert attempt["provider_wire_requested_output_cap"] > 0

    records = {
        (record["provider_operator"], record["model"]): record
        for record in admission["route_records"]
    }
    assert records[("DEEPSEEK_OFFICIAL", "deepseek-v4-pro")]["admission_result"] == "PASS"
    assert records[("THIRD_PARTY_ENDPOINT_LOCAL_METADATA_ONLY", "doubao-seed-character-260628")]["admission_result"] == "PASS"
    assert records[("THIRD_PARTY_ENDPOINT_LOCAL_METADATA_ONLY", "qwen-3.7-plus")]["admission_result"] == "BLOCKED"
    assert records[("THIRD_PARTY_ENDPOINT_LOCAL_METADATA_ONLY", "gpt-5.6-sol")]["admission_result"] == "BLOCKED"
    assert records[("THIRD_PARTY_ENDPOINT_LOCAL_METADATA_ONLY", "claude-sonnet-5")]["admission_result"] == "BLOCKED"


def test_all_json_receipts_seal_the_offline_boundary_and_manifest() -> None:
    for name in REQUIRED - {"README.md"}:
        path = ROOT / name
        document = json.loads(path.read_text(encoding="utf-8"))
        assert document["external_boundary"] == ZERO_BOUNDARY
        assert document["current_model_route_scheduling_changed"] is False

    manifest = _load("sha256-manifest-v1.json")
    for name, metadata in manifest["files"].items():
        payload = (ROOT / name).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == metadata["sha256"]
        assert len(payload) == metadata["bytes"]
