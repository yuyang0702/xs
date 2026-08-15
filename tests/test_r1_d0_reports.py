import hashlib
import json
from pathlib import Path


REPORTS = Path("docs/superpowers/reports/r1-d0")


def _load(name: str) -> dict:
    return json.loads((REPORTS / name).read_text(encoding="utf-8"))


def test_failure_timeline_has_exact_three_attempts_and_first_divergence() -> None:
    value = _load("draft-prose-validation-failure-timeline-v1.json")

    assert [item["ordinal"] for item in value["timeline"]] == [20, 21, 22]
    assert [item["concrete_blocker_count"] for item in value["timeline"]] == [6, 7, 1]
    assert value["first_divergent_node"] == {
        "call_ordinal": 20,
        "function": "novel_flywheel.prose_quality.analyze_prose",
        "rule": "MIXED_SCRIPT",
        "issue_code": "mixed_script_corruption",
        "confidence": "high",
    }


def test_scope_retry_report_does_not_claim_a_patch_contract() -> None:
    value = _load("draft-scope-retry-closure-map-v1.json")

    assert value["scope_kind"] == "whole_ownership_unit_regeneration"
    assert value["missing_bindings"]["previous_draft_hash"] == "not supplied"
    assert value["missing_bindings"]["formal_issue_receipt"] == "not materialized"
    assert value["closure_classification"] == "target_partially_reduced_but_not_eliminated"


def test_containment_report_does_not_promote_a_rejected_stage_output() -> None:
    value = _load("draft-best-candidate-containment-v1.json")

    assert value["candidate_rows_for_run"] == 0
    assert value["diagnostic_best_output"]["formal_candidate"] is False
    assert value["diagnostic_best_output"]["promotable"] is False
    assert value["resume_behavior"]["recoverable_legal_draft"] is False


def test_offline_replay_proves_zero_external_or_paid_boundaries() -> None:
    value = _load("r1-d0-exact-offline-replay-v1.json")

    assert value["production_provider_calls"] == 0
    assert value["credential_lookups"] == 0
    assert value["provider_client_constructions"] == 0
    assert value["network_calls"] == 0
    assert value["paid_model_calls"] == 0
    assert value["fake_boundaries"] == 3
    assert value["result"] == "exact_terminal_reproduced"


def test_hypothesis_table_preserves_supported_contradicted_and_unknown() -> None:
    value = _load("r1-d0-hypothesis-table-v1.json")
    statuses = {item["id"]: item["status"] for item in value["hypotheses"]}

    assert statuses["H5"] == "confirmed"
    assert statuses["H1"] == "contradicted"
    assert statuses["H8"] == "unresolved_policy_question"
    assert value["suggested_failure_family"] == "draft.validator_false_positive"


def test_committed_r1_d0_evidence_contains_no_raw_private_material() -> None:
    forbidden = (
        "api_key",
        "authorization: bearer",
        "raw_prompt",
        "story_text",
        "\\.tmp\\pa-strict",
        "/.tmp/pa-strict",
    )
    for path in REPORTS.glob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8").casefold()
        for marker in forbidden:
            assert marker not in text, f"{path.name} contains forbidden marker {marker}"


def test_forward_risk_declares_no_model_output_boundary_change() -> None:
    value = _load("r1-d0-forward-risk-v2.json")

    assert value["resolution_status"] == "unresolved"
    assert value["model_output_boundary_changed"] is False
    assert "not_applicable" in {
        item["disposition"] for item in value["sibling_boundaries"]
    }


def test_evidence_index_binds_every_deliverable_byte_for_byte() -> None:
    value = _load("r1-d0-evidence-index-v1.json")

    assert value["row_count"] == len(value["rows"]) == 10
    for row in value["rows"]:
        data = (REPORTS / row["path"]).read_bytes()
        assert len(data) == row["bytes"]
        assert hashlib.sha256(data).hexdigest() == row["sha256"]
    canonical = json.dumps(
        value["rows"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    assert hashlib.sha256(canonical).hexdigest() == value["rows_canonical_sha256"]
