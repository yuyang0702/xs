from __future__ import annotations

import json
from pathlib import Path

from tools.diagnostics import skill_v2_creative_restoration as restoration


REPO = Path(__file__).resolve().parents[1]
IMPLEMENTATION_HEAD = "03258b82c74f1875b86e1569e56d6e90b9a274ed"


def _documents():
    return restoration.build_documents(REPO, IMPLEMENTATION_HEAD)


def _json(documents: dict[str, bytes], relative: str):
    return json.loads(documents[relative].decode("utf-8"))


def _assert_manifest_exact(documents: dict[str, bytes], relative: str) -> None:
    manifest = _json(documents, relative)
    assert manifest["entry_count"] == len(manifest["files"])
    assert manifest["overall_status"] == "exact"
    for entry in manifest["files"]:
        data = documents[entry["path"]]
        assert entry["bytes"] == len(data)
        assert entry["sha256"] == restoration._sha_bytes(data)


def test_successor_evidence_is_exact_complete_and_hash_bound():
    evidence, packet, result = _documents()
    assert result["overall_status"] == "exact"
    assert result["restoration_item_count"] == 8
    assert result["old_quality"] == "fail"
    assert result["creative_gate"] == "pass"
    assert result["resolver_parity"] == "exact"
    assert result["restored_context_char_count"] <= 3000
    assert result["external_actions"] == restoration._external_actions()
    assert len(evidence) == 19
    assert len(packet) == 17
    _assert_manifest_exact(
        evidence, f"{restoration.RESTORATION_ROOT}/sha256-manifest-v1.json",
    )
    _assert_manifest_exact(
        packet, f"{restoration.MATERIALIZATION_ROOT}/sha256-manifest-v1.json",
    )


def test_exact_eight_item_matrix_and_budget_are_not_silently_narrowed():
    evidence, _, _ = _documents()
    matrix = _json(
        evidence,
        f"{restoration.RESTORATION_ROOT}/restoration-implementation-matrix-v1.json",
    )
    context = _json(
        evidence,
        f"{restoration.RESTORATION_ROOT}/old-vs-restored-context-diff-v1.json",
    )
    assert matrix["restoration_items_expected"] == 8
    assert matrix["restoration_items_implemented"] == 8
    assert matrix["unplanned_restoration_items"] == 0
    assert [row["restoration_id"] for row in matrix["rows"]] == list(
        restoration.RESTORED_CREATIVE_RULE_IDS
    )
    assert all(row["local_validator_can_replace"] is False for row in matrix["rows"])
    assert context["old_rendered_context_char_count"] == 1587
    assert context["new_rendered_context_char_count"] == 2742
    assert context["char_delta"] == 1155
    assert context["mandatory_characters"] == 1155
    assert context["advisory_characters"] == 1587
    assert context["context_hard_ceiling_chars"] == 3000
    assert context["truncation_status"] == "NONE"
    assert context["excluded_rule_ids"] == []


def test_actionable_quality_successor_rejects_old_and_all_negative_cases():
    evidence, _, _ = _documents()
    quality = _json(
        evidence,
        f"{restoration.RESTORATION_ROOT}/offline-quality-successor-v1.json",
    )
    anti = _json(
        evidence,
        f"{restoration.RESTORATION_ROOT}/anti-overcompression-matrix-v1.json",
    )
    leaks = _json(
        evidence,
        f"{restoration.RESTORATION_ROOT}/do-not-restore-regression-v1.json",
    )
    assert quality["old_overcompressed_profile_offline_quality"] == "FAIL_EXPECTED"
    assert quality["restored_profile_offline_quality"] == "PASS"
    assert quality["offline_capability_audit_false_positive_closed"] is True
    assert anti["overall_status"] == "exact"
    assert anti["case_count"] == 6
    assert all(row["actual"] == "fail" for row in anti["cases"])
    assert leaks["total_leak_count"] == 0


def test_resolver_ab_lock_and_reliability_bindings_remain_exact():
    evidence, packet, _ = _documents()
    resolver = _json(
        evidence, f"{restoration.RESTORATION_ROOT}/resolver-parity-v1.json",
    )
    lock = _json(
        evidence, f"{restoration.RESTORATION_ROOT}/ab-semantic-lock-v1.json",
    )
    runtime = _json(
        packet, f"{restoration.MATERIALIZATION_ROOT}/restored-b-runtime-binding-v1.json",
    )
    assert resolver["resolver_source_changed"] is False
    assert resolver["resolver_predicates_changed"] is False
    assert resolver["resolver_load_policy_changed"] is False
    assert resolver["decision_equal"] is True
    assert lock["primary_changed_variable"] == "SKILL_CONTEXT"
    diff_counts = [
        value for key, value in lock.items()
        if key.endswith("_diff_count")
    ]
    assert diff_counts and set(diff_counts) == {0}
    assert runtime["single_dispatch_per_arm"] is True
    assert runtime["sdk_retries_allowed"] is False
    assert runtime["transport_request_retries_allowed"] is False
    assert runtime["route_fallback_after_dispatch_allowed"] is False


def test_fresh_candidate_is_disabled_unused_unreserved_and_inert():
    _, packet, _ = _documents()
    candidate = _json(
        packet, f"{restoration.MATERIALIZATION_ROOT}/restored-b-candidate-v1.json",
    )
    assert candidate["scope"] == restoration.CANDIDATE_SCOPE
    assert candidate["cohort_id"] == restoration.COHORT_ID
    assert candidate["implementation_head"] == IMPLEMENTATION_HEAD
    assert candidate["execution_authorized"] is False
    assert candidate["usage_status"] == "unused"
    assert candidate["reservation_status"] == "unreserved"
    assert candidate["named_approver"] is None
    assert candidate["signed_approval"] == "ABSENT"
    assert candidate["single_use_nonce"] is None
    assert candidate["approval_reuse_allowed"] is False
    assert candidate["cohort_reuse_allowed"] is False
    assert candidate["full_short_authorized"] is False
    assert candidate["skill_v2_production_cutover_authorized"] is False
    assert set(candidate["external_actions"].values()) == {0}
    assert not any("approval" in path.lower() for path in packet)
    assert not any("nonce" in path.lower() for path in packet)


def test_bounded_repeated_design_is_five_pairs_and_not_executable():
    evidence, _, _ = _documents()
    design = _json(
        evidence,
        f"{restoration.RESTORATION_ROOT}/bounded-repeated-ab-design-v1.json",
    )
    rule = _json(
        evidence,
        f"{restoration.RESTORATION_ROOT}/future-ab-decision-rule-v1.json",
    )
    assert design["pair_count"] == 5
    assert len(design["pairs"]) == 5
    assert design["execution_status"] == "NOT_EXECUTED"
    assert design["blanket_batch_approval_allowed"] is False
    assert all(row["a_arm_required"] and row["b_arm_required"] for row in design["pairs"])
    assert all(row["single_dispatch_per_arm"] for row in design["pairs"])
    assert rule["critical_narrative_regression"] == "NO_GO"
    assert rule["engineering_failure_or_regression"] == "NO_GO"
    assert rule["token_reduction_can_override_quality_regression"] is False
    assert rule["production_cutover_authorized"] is False


def test_materializer_writes_only_new_roots(tmp_path: Path):
    evidence, packet, _ = _documents()
    restoration.write_documents(tmp_path, {**evidence, **packet})
    actual = {
        path.relative_to(tmp_path).as_posix()
        for path in tmp_path.rglob("*") if path.is_file()
    }
    assert actual == set(evidence) | set(packet)


def test_materialized_repository_bytes_are_exact_when_present():
    evidence, packet, _ = _documents()
    for relative, expected in {**evidence, **packet}.items():
        path = REPO / relative
        if path.exists():
            assert path.read_bytes() == expected
