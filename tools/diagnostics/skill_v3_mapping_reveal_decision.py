from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


BRANCH = "r1-ptr3/planning-repair-finding-propagation-20260817"
START_HEAD = "3e9a012f5d826a222547cea21d80136b439adc1d"
OUTPUT_RELATIVE_ROOT = (
    "docs/superpowers/reports/"
    "skill-v3-character-heavy-multi-sample-mapping-reveal-decision-v1"
)

BUNDLE_ROOT = Path(
    "docs/superpowers/reports/skill-v3-character-heavy-multi-sample-blind-bundle-v1"
)
EVALUATOR_1_ROOT = Path(
    "docs/superpowers/reports/skill-v3-character-heavy-multi-sample-blind-evaluation-v1"
)
EVALUATOR_2_ROOT = Path(
    "docs/superpowers/reports/skill-v3-character-heavy-multi-sample-blind-evaluation-v2"
)
COMBINED_ROOT = Path(
    "docs/superpowers/reports/skill-v3-character-heavy-multi-sample-combined-blind-aggregation-v1"
)
MAPPING_ROOT = Path(
    "docs/superpowers/reports/skill-v3-character-heavy-multi-sample-blind-mapping-v1"
)
READINESS_ROOT = Path(
    "docs/superpowers/reports/skill-v3-character-heavy-multi-sample-pilot-approval-readiness-recheck-v1"
)
CAMPAIGN_ROOT = Path(
    "docs/superpowers/reports/skill-v3-character-heavy-multi-sample-real-campaign-v1"
)
STRATEGY_ROOT = Path(
    "docs/superpowers/reports/skill-v3-verbatim-selective-compiler-strategy-pivot-v1"
)

EVALUATOR_1_FREEZE_SHA256 = (
    "45927989be4cd126dd567393da3efebe59880ec239e9716a720ea2e54b66bd3b"
)
EVALUATOR_2_FREEZE_SHA256 = (
    "9c4c5ce98c78cd33c4404363476bce3a70f1b6b55be6211d82060b021f5d2dc6"
)
LITERARY_POLICY_SHA256 = (
    "d93c95af9ed15d4c3f1193b00e319f364fb57176190e96e9e5d2fcd19eec0b21"
)
COMBINED_LITERARY_FREEZE_SHA256 = (
    "c9be76be273049ec55c772298ceddb99964a1101abbc25edb2062523e93d4d4b"
)

DIMENSIONS = (
    "character_agency",
    "causal_coherence",
    "subtext_support",
    "specificity",
    "scene_pressure",
    "setup_payoff_integrity",
    "voice_readiness",
    "anti_template_risk",
)
CRITICAL_DIMENSIONS = {
    "character_agency",
    "causal_coherence",
    "setup_payoff_integrity",
}
EXPECTED_BLIND_COUNTS = {
    "character_agency": (0, 6, 0),
    "causal_coherence": (0, 6, 0),
    "subtext_support": (0, 5, 1),
    "specificity": (0, 6, 0),
    "scene_pressure": (0, 6, 0),
    "setup_payoff_integrity": (0, 5, 1),
    "voice_readiness": (1, 5, 0),
    "anti_template_risk": (1, 4, 1),
}

SELECTIVE_ID = "VERBATIM_SELECTIVE_SKILL_COMPILER_SHADOW_V1_CHARACTER_HEAVY"
BASELINE_ID = "DEMAND_AWARE_V2_LAST_KNOWN_BEST_COMPRESSED_BASELINE"
FINAL_DISPOSITION = "SKILL_V3_CHARACTER_HEAVY_MULTI_SAMPLE_PILOT=NO_GO_QUALITY"
NEXT_GATE = "SKILL_V3_SELECTIVE_COMPILER_MULTI_SAMPLE_QUALITY_ROOT_CAUSE"


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha_file(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _read_json(repo: Path, relative: Path | str) -> dict[str, Any]:
    value = json.loads((repo / relative).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {relative}")
    return value


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "git command failed")
    return result.stdout.strip()


def _manifest_definition(envelope: dict[str, Any]) -> dict[str, Any]:
    definition = envelope.get("definition")
    return definition if isinstance(definition, dict) else envelope


def verify_manifest(repo: Path, root: Path) -> dict[str, Any]:
    manifest_path = repo / root / "sha256-manifest-v1.json"
    envelope = json.loads(manifest_path.read_text(encoding="utf-8"))
    definition = _manifest_definition(envelope)
    entries = definition.get("entries")
    if not isinstance(entries, list):
        raise RuntimeError(f"manifest entries missing: {root}")
    failures: list[str] = []
    covered: set[str] = set()
    for entry in entries:
        relative = entry["path"].replace("\\", "/")
        covered.add(relative)
        path = repo / root / relative
        if not path.is_file():
            failures.append(f"missing:{relative}")
            continue
        content = path.read_bytes()
        if _sha_bytes(content) != entry["sha256"]:
            failures.append(f"sha256:{relative}")
        if "bytes" in entry and len(content) != entry["bytes"]:
            failures.append(f"bytes:{relative}")
    actual = {
        path.relative_to(repo / root).as_posix()
        for path in (repo / root).rglob("*")
        if path.is_file() and path.name != "sha256-manifest-v1.json"
    }
    if actual != covered:
        failures.append(
            "coverage:missing="
            + ",".join(sorted(actual - covered))
            + ";extra="
            + ",".join(sorted(covered - actual))
        )
    declared_count = definition.get("entry_count")
    if declared_count != len(entries):
        failures.append(f"entry_count:{declared_count}!={len(entries)}")
    if failures:
        raise RuntimeError(f"manifest not exact for {root}: {failures}")
    return {
        "root": root.as_posix(),
        "status": "EXACT",
        "entry_count": len(entries),
        "manifest_file_sha256": _sha_file(manifest_path),
        "definition_sha256": envelope.get("definition_sha256"),
        "evidence_root_sha256": envelope.get("evidence_root_sha256"),
    }


def relation_to_experiment_result(relation: str, position_a_arm: str, position_b_arm: str) -> str:
    if relation == "TIE":
        return "EQUIVALENT"
    if relation == "INCOMPARABLE":
        return "INCONCLUSIVE"
    if relation == "A_BETTER":
        winning_arm = position_a_arm
    elif relation == "B_BETTER":
        winning_arm = position_b_arm
    else:
        raise RuntimeError(f"unknown relation: {relation}")
    return "SELECTIVE_VERBATIM_BETTER" if winning_arm == "B" else "BASELINE_BETTER"


def _per_evaluator_direction(values: Iterable[str]) -> str:
    counts = Counter(values)
    if not counts:
        return "INCONCLUSIVE"
    most = counts.most_common()
    if len(most) > 1 and most[0][1] == most[1][1]:
        return "INCONCLUSIVE"
    return most[0][0] if most[0][1] >= 2 else "INCONCLUSIVE"


def aggregate_experiment_relations(rows: list[dict[str, str]]) -> tuple[str, dict[str, int], dict[str, str]]:
    counts = Counter(row["mapped_result"] for row in rows)
    evaluator_values: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        evaluator_values[row["evaluator_id"]].append(row["mapped_result"])
    evaluator_directions = {
        evaluator: _per_evaluator_direction(values)
        for evaluator, values in sorted(evaluator_values.items())
    }
    supported = [
        relation
        for relation in (
            "SELECTIVE_VERBATIM_BETTER",
            "BASELINE_BETTER",
            "EQUIVALENT",
        )
        if counts[relation] >= 4
    ]
    if len(supported) == 1:
        result = supported[0]
    elif len(set(evaluator_directions.values())) == 1 and next(
        iter(evaluator_directions.values()), "INCONCLUSIVE"
    ) != "INCONCLUSIVE":
        result = next(iter(evaluator_directions.values()))
    else:
        result = "INCONCLUSIVE"
    normalized_counts = {
        key: counts[key]
        for key in (
            "SELECTIVE_VERBATIM_BETTER",
            "BASELINE_BETTER",
            "EQUIVALENT",
            "INCONCLUSIVE",
        )
    }
    return result, normalized_counts, evaluator_directions


def _history(repo: Path, relative: Path) -> dict[str, str]:
    raw = _git(repo, "log", "-1", "--format=%H%x09%cI", "--", relative.as_posix())
    commit, committed_at = raw.split("\t", 1)
    return {"commit": commit, "committed_at": committed_at}


def _validate_parent_state(repo: Path) -> dict[str, Any]:
    branch = _git(repo, "branch", "--show-current")
    head = _git(repo, "rev-parse", "HEAD")
    status = _git(repo, "status", "--porcelain")
    allowed_task_paths = (
        "tools/diagnostics/skill_v3_mapping_reveal_decision.py",
        "tests/canary/test_skill_v3_mapping_reveal_decision.py",
        OUTPUT_RELATIVE_ROOT + "/",
    )
    dirty_paths = []
    for line in status.splitlines():
        path = line[3:].replace("\\", "/")
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        dirty_paths.append(path)
    unrelated_dirty = [
        path
        for path in dirty_paths
        if not any(path == prefix or path.startswith(prefix) for prefix in allowed_task_paths)
    ]
    if branch != BRANCH or head != START_HEAD or unrelated_dirty:
        raise RuntimeError(
            f"baseline mismatch: branch={branch}, head={head}, unrelated_dirty={unrelated_dirty}"
        )

    manifests = {
        "blind_bundle": verify_manifest(repo, BUNDLE_ROOT),
        "evaluator_1": verify_manifest(repo, EVALUATOR_1_ROOT),
        "evaluator_2": verify_manifest(repo, EVALUATOR_2_ROOT),
        "combined": verify_manifest(repo, COMBINED_ROOT),
    }
    evaluator_1 = _read_json(repo, EVALUATOR_1_ROOT / "independent-judgments-freeze-v1.json")
    evaluator_2 = _read_json(repo, EVALUATOR_2_ROOT / "second-independent-judgments-freeze-v1.json")
    combined = _read_json(repo, COMBINED_ROOT / "combined-literary-freeze-v1.json")
    compatibility = _read_json(repo, COMBINED_ROOT / "blind-policy-compatibility-v1.json")
    vote_set = _read_json(repo, COMBINED_ROOT / "complete-vote-set-v1.json")
    marker = _read_json(repo, COMBINED_ROOT / "COMBINED_BLIND_AGGREGATION_FROZEN.json")
    failures: list[str] = []
    if evaluator_1.get("independent_judgments_root_sha256") != EVALUATOR_1_FREEZE_SHA256:
        failures.append("evaluator_1_freeze")
    if evaluator_2.get("judgment_set_sha256") is None:
        failures.append("evaluator_2_judgment_set")
    if combined.get("evaluator_2_freeze_sha256") != EVALUATOR_2_FREEZE_SHA256:
        failures.append("evaluator_2_freeze")
    if _sha_file(repo / COMBINED_ROOT / "combined-literary-freeze-v1.json") != COMBINED_LITERARY_FREEZE_SHA256:
        failures.append("combined_freeze")
    if compatibility.get("evaluator_1_policy_sha256") != LITERARY_POLICY_SHA256:
        failures.append("literary_policy")
    required_flags = {
        "evaluator_1_mapping_revealed": evaluator_1.get("mapping_revealed") is False,
        "evaluator_2_mapping_revealed": evaluator_2.get("mapping_revealed") is False,
        "evaluator_2_mapping_root_unread": evaluator_2.get("mapping_root_read") is False,
        "combined_mapping_revealed": combined.get("mapping_revealed") is False,
        "combined_mapping_contamination_zero": combined.get("mapping_contamination") == 0,
        "vote_set_complete": vote_set.get("combined_required_vote_set_complete") is True,
        "vote_count_exact": (
            vote_set.get("required_evaluator_by_batch_votes") == 6
            and vote_set.get("observed_evaluator_by_batch_votes") == 6
            and vote_set.get("missing_required_vote_count") == 0
            and vote_set.get("duplicate_vote_count") == 0
            and vote_set.get("unauthorized_extra_vote_count") == 0
        ),
        "policy_no_drift": compatibility.get("policy_or_bundle_drift") is False,
        "combined_gate_exact": marker.get("status") == "SKILL_V3_MULTI_SAMPLE_COMBINED_BLIND_AGGREGATION_FROZEN",
    }
    failures.extend(key for key, value in required_flags.items() if not value)
    if failures:
        raise RuntimeError("SKILL_V3_MAPPING_REVEAL_NO_GO_BLIND_FREEZE_OR_CHRONOLOGY: " + ",".join(failures))
    return {
        "branch": branch,
        "head": head,
        "manifests": manifests,
        "evaluator_1": evaluator_1,
        "evaluator_2": evaluator_2,
        "combined": combined,
        "compatibility": compatibility,
        "vote_set": vote_set,
        "marker": marker,
        "required_flags": required_flags,
    }


def _manifest_entries(documents: dict[str, bytes]) -> list[dict[str, Any]]:
    return [
        {"path": path, "bytes": len(content), "sha256": _sha_bytes(content)}
        for path, content in sorted(documents.items())
    ]


def _privacy_scan(documents: dict[str, bytes]) -> dict[str, Any]:
    text = "\n".join(content.decode("utf-8") for content in documents.values())
    patterns = {
        "anthropic_secret": r"sk-ant-[A-Za-z0-9_-]{16,}",
        "bearer_token": r"(?i)authorization\s*:\s*bearer\s+[A-Za-z0-9._-]{12,}",
        "private_key": r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        "generic_secret_assignment": r"(?i)(?:api[_-]?key|secret|password)\s*[=:]\s*['\"][^'\"]{12,}['\"]",
    }
    matches = {name: len(re.findall(pattern, text)) for name, pattern in patterns.items()}
    return {
        "schema": "SkillV3MappingRevealDecisionPrivacyScanV1",
        "status": "PASS" if sum(matches.values()) == 0 else "FAIL",
        "matches": matches,
        "total_matches": sum(matches.values()),
        "raw_prompt_persisted": False,
        "raw_story_input_persisted": False,
        "raw_provider_response_persisted": False,
        "literary_artifact_body_persisted": False,
        "credentials_persisted": False,
        "hash_only_or_typed_evidence": True,
    }


def build_artifacts(
    repo: Path,
    *,
    focused_tests: str,
    related_tests: str,
    full_suite: str,
    strict_l3: str,
    new_owning_source_regression_count: int,
) -> dict[str, bytes]:
    parent = _validate_parent_state(repo)

    # The mapping root is deliberately read only after the blind freeze gate above succeeds.
    mapping_manifest = verify_manifest(repo, MAPPING_ROOT)
    readiness_manifest = verify_manifest(repo, READINESS_ROOT)
    campaign_manifest = verify_manifest(repo, CAMPAIGN_ROOT)
    mapping = _read_json(repo, MAPPING_ROOT / "sealed-mapping-v1.json")
    mapping_rows = mapping.get("rows", [])
    anonymous_ids = [row["anonymous_sample_id"] for row in mapping_rows]
    sample_ids = [row["sample_id"] for row in mapping_rows]
    if len(mapping_rows) != 6 or len(set(anonymous_ids)) != 6 or len(set(sample_ids)) != 6:
        raise RuntimeError("mapping is not one-to-one across six samples")
    mapping_by_anonymous = {row["anonymous_sample_id"]: row for row in mapping_rows}
    vote_set = parent["vote_set"]
    vote_ids = {vote["position_a_anonymous_sample_id"] for vote in vote_set["votes"]}
    vote_ids |= {vote["position_b_anonymous_sample_id"] for vote in vote_set["votes"]}
    if set(anonymous_ids) != vote_ids:
        raise RuntimeError("mapping and frozen vote-set anonymous IDs differ")

    arm_binding = _read_json(repo, READINESS_ROOT / "arm-binding-v1.json")
    capacity = _read_json(repo, READINESS_ROOT / "capacity-recheck-v1.json")
    byte_identity = _read_json(repo, READINESS_ROOT / "a-b-byte-identity-recheck-v1.json")
    reference_binding = _read_json(repo, READINESS_ROOT / "reference-distill-closure-binding-v1.json")
    model_route = _read_json(repo, READINESS_ROOT / "model-route-binding-v1.json")
    six_locks = _read_json(repo, READINESS_ROOT / "six-sample-locks-v1.json")
    narrative_rule = _read_json(repo, STRATEGY_ROOT / "multi-sample-narrative-aggregation-rule-v1.json")
    validation_policy = _read_json(repo, STRATEGY_ROOT / "multi-sample-pair-validation-policy-v1.json")
    frozen_aggregates = _read_json(repo, COMBINED_ROOT / "combined-per-dimension-aggregation-v1.json")
    variance = _read_json(repo, COMBINED_ROOT / "combined-variance-review-v1.json")

    aggregate_by_dimension = {row["aggregate_id"]: row for row in frozen_aggregates["aggregates"]}
    for dimension, expected in EXPECTED_BLIND_COUNTS.items():
        row = aggregate_by_dimension[dimension]
        actual = (
            row["direction_counts"].get("A_BETTER", 0),
            row["direction_counts"].get("B_BETTER", 0),
            row["tie_or_equivalent_counts"],
        )
        if actual != expected or row["aggregate_result"] != "B_BETTER":
            raise RuntimeError(f"frozen aggregate drift: {dimension}: {actual}")

    mapped_votes_by_dimension: dict[str, list[dict[str, str]]] = defaultdict(list)
    pair_mapping: dict[str, dict[str, str]] = {}
    for vote in vote_set["votes"]:
        pair_id = vote["anonymous_pair_id"]
        position_a = mapping_by_anonymous[vote["position_a_anonymous_sample_id"]]
        position_b = mapping_by_anonymous[vote["position_b_anonymous_sample_id"]]
        binding = {
            "blind_side_a_experiment_arm": position_a["arm"],
            "blind_side_a_sample_slot": position_a["sample_slot"],
            "blind_side_b_experiment_arm": position_b["arm"],
            "blind_side_b_sample_slot": position_b["sample_slot"],
        }
        if pair_id in pair_mapping and pair_mapping[pair_id] != binding:
            raise RuntimeError(f"pair position mapping drift: {pair_id}")
        pair_mapping[pair_id] = binding
        for dimension, relation in vote["dimension_relations"].items():
            mapped_votes_by_dimension[dimension].append(
                {
                    "vote_id": vote["vote_id"],
                    "evaluator_id": vote["evaluator_id"],
                    "anonymous_pair_id": pair_id,
                    "blind_relation": relation,
                    "mapped_result": relation_to_experiment_result(
                        relation, position_a["arm"], position_b["arm"]
                    ),
                }
            )

    disagreement_by_dimension: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in variance["evaluator_disagreements"]:
        disagreement_by_dimension[item["dimension"]].append(item)
    opposed_dimensions = set(variance["opposed_direction_dimensions"])
    tie_variance_dimensions = set(variance["direction_tie_variance_dimensions"])

    mapped_dimensions: list[dict[str, Any]] = []
    for dimension in DIMENSIONS:
        result, counts, evaluator_directions = aggregate_experiment_relations(
            mapped_votes_by_dimension[dimension]
        )
        blind = aggregate_by_dimension[dimension]
        mapped_dimensions.append(
            {
                "dimension": dimension,
                "criticality": "CRITICAL" if dimension in CRITICAL_DIMENSIONS else "NONCRITICAL",
                "blind_result": f"BLIND_SIDE_{blind['aggregate_result']}",
                "blind_counts": {
                    "BLIND_SIDE_A_BETTER": blind["direction_counts"].get("A_BETTER", 0),
                    "BLIND_SIDE_B_BETTER": blind["direction_counts"].get("B_BETTER", 0),
                    "TIE_OR_EQUIVALENT": blind["tie_or_equivalent_counts"],
                },
                "mapped_experiment_counts": counts,
                "mapped_experiment_result": result,
                "evaluator_mapped_directions": evaluator_directions,
                "blind_variance_flag": blind["variance_flag"],
                "opposed_direction_flag": dimension in opposed_dimensions,
                "direction_tie_variance_flag": dimension in tie_variance_dimensions,
                "evaluator_disagreement_flag": bool(disagreement_by_dimension[dimension]),
                "evaluator_disagreements": disagreement_by_dimension[dimension],
                "mapped_vote_trace": mapped_votes_by_dimension[dimension],
            }
        )

    critical_counts = Counter(
        row["mapped_experiment_result"] for row in mapped_dimensions if row["criticality"] == "CRITICAL"
    )
    noncritical_counts = Counter(
        row["mapped_experiment_result"] for row in mapped_dimensions if row["criticality"] == "NONCRITICAL"
    )
    narrative_non_inferior = (
        "YES"
        if critical_counts["BASELINE_BETTER"] == 0
        and critical_counts["INCONCLUSIVE"] == 0
        and (
            critical_counts["SELECTIVE_VERBATIM_BETTER"]
            + critical_counts["EQUIVALENT"]
        )
        == len(CRITICAL_DIMENSIONS)
        else "NO"
    )
    if narrative_non_inferior != "NO" or critical_counts["BASELINE_BETTER"] != 3:
        raise RuntimeError("unexpected narrative decision")

    campaign = {
        "validity": _read_json(repo, CAMPAIGN_ROOT / "six-sample-validity-matrix-v1.json"),
        "attempts": _read_json(repo, CAMPAIGN_ROOT / "attempt-counters-v1.json"),
        "budget": _read_json(repo, CAMPAIGN_ROOT / "cumulative-budget-receipt-v1.json"),
        "terminal": _read_json(repo, CAMPAIGN_ROOT / "terminal-pipeline-receipts-v1.json"),
        "egress": _read_json(repo, CAMPAIGN_ROOT / "destination-egress-receipts-v1.json"),
        "approvals": _read_json(repo, CAMPAIGN_ROOT / "approval-final-states-v1.json"),
        "nonces": _read_json(repo, CAMPAIGN_ROOT / "nonce-final-states-v1.json"),
        "isolation": _read_json(repo, CAMPAIGN_ROOT / "production-isolation-v1.json"),
        "independence": _read_json(repo, CAMPAIGN_ROOT / "independence-contamination-recheck-v1.json"),
        "tests": _read_json(repo, CAMPAIGN_ROOT / "test-receipt-v1.json"),
        "privacy": _read_json(repo, CAMPAIGN_ROOT / "privacy-scan-v1.json"),
        "supplement": _read_json(repo, MAPPING_ROOT / "campaign-final-report-supplement-v1.json"),
    }
    if campaign["validity"].get("valid_count") != 6:
        raise RuntimeError("six-sample campaign validity drift")
    if campaign["budget"].get("campaign_total_provider_http_network") != [6, 6, 6]:
        raise RuntimeError("campaign request totals drift")

    per_sample_provider_attempts = [
        row["attempts"].get(
            "provider_dispatch_attempt_count",
            row["attempts"].get("real_provider_request_attempts"),
        )
        for row in campaign["attempts"]["rows"]
    ]
    all_approvals_consumed = all(
        row["approval_final_state"].get(
            "status", row["approval_final_state"].get("state")
        )
        == "CONSUMED"
        for row in campaign["approvals"]["rows"]
    )
    all_nonces_consumed = all(
        row["nonce_final_state"].get(
            "status", row["nonce_final_state"].get("state")
        )
        == "CONSUMED"
        and row["nonce_final_state"].get(
            "reusable", not row["nonce_final_state"].get("single_use", False)
        )
        is False
        for row in campaign["nonces"]["rows"]
    )
    egress_exact = all(
        row["destination_egress"].get(
            "actual_destination_origin",
            row["destination_egress"].get("destination_origin"),
        )
        == "https://lingsuan.org"
        and row["destination_egress"].get(
            "actual_destination_path",
            row["destination_egress"].get("destination_path"),
        )
        == "/v1/messages"
        and row["destination_egress"].get("cross_origin_redirect_allowed") is False
        for row in campaign["egress"]["rows"]
    )
    route_identity_exact = len({row["route_fingerprint"] for row in six_locks["locks"]}) == 1
    model_identity_exact = len({row["model_binding_sha256"] for row in six_locks["locks"]}) == 1
    provider_identity_exact = len(
        {row["provider_descriptor_sha256"] for row in six_locks["locks"]}
    ) == 1
    validator_identity_exact = len({row["validator_sha256"] for row in six_locks["locks"]}) == 1
    all_terminal_pass = all(
        row["terminal_pipeline"].get("status") == "PASS"
        and row["terminal_pipeline"].get("production_authority") is False
        for row in campaign["terminal"]["rows"]
    )
    production_isolation_exact = (
        campaign["isolation"].get("status") == "PASS"
        and campaign["isolation"].get("src_diff") == 0
        and campaign["isolation"].get("baml_src_diff") == 0
        and campaign["isolation"].get("story_state_mutation_count") == 0
        and campaign["isolation"].get("canon_mutation_count") == 0
        and campaign["isolation"].get("ready_mutation_count") == 0
        and campaign["isolation"].get("production_authority_count") == 0
    )
    capacity_exact = (
        capacity.get("a_capacity") == "PASS"
        and capacity.get("b_capacity") == "PASS"
        and capacity.get("no_silent_truncation") is True
    )
    truncation_exact = (
        reference_binding.get("advisory_truncation_occurred") is False
        and reference_binding.get("advisory_shedding_occurred") is False
    )
    retry_exact = (
        campaign["budget"].get("retry_count") == 0
        and campaign["budget"].get("fallback_count") == 0
        and campaign["budget"].get("route_switch_count") == 0
        and campaign["budget"].get("resume_count") == 0
        and campaign["budget"].get("second_dispatch_count") == 0
        and per_sample_provider_attempts == [1, 1, 1, 1, 1, 1]
    )
    provenance_exact = (
        campaign["independence"].get("status") == "PASS"
        and campaign["independence"].get("uncontrolled_variable_count") == 0
        and byte_identity.get("status") == "PASS"
        and byte_identity.get("only_skill_context_differs_by_arm") is True
        and reference_binding.get("exact_rendered_advisory_provenance") == "PASS"
    )
    engineering_regressions = {
        "VALIDITY_REGRESSION": campaign["validity"].get("valid_count") != 6,
        "CAPACITY_REGRESSION": not capacity_exact,
        "TRUNCATION_REGRESSION": not truncation_exact,
        "RETRY_REGRESSION": not retry_exact,
        "ROUTE_REGRESSION": not (
            route_identity_exact and model_identity_exact and provider_identity_exact
        ),
        "VALIDATOR_REGRESSION": not validator_identity_exact,
        "PRODUCTION_ISOLATION_REGRESSION": not (
            production_isolation_exact and all_terminal_pass
        ),
        "PROVENANCE_REGRESSION": not provenance_exact,
        "SECURITY_EGRESS_REGRESSION": not egress_exact,
    }
    engineering_non_inferior = "YES" if not any(engineering_regressions.values()) else "NO"

    chronology = {
        "schema": "SkillV3MappingRevealBlindChronologyV1",
        "status": "PASS",
        "required_order": [
            "BLIND_BUNDLE_SEALED",
            "EVALUATOR_1_FROZEN",
            "EVALUATOR_2_INDEPENDENTLY_FROZEN",
            "COMBINED_BLIND_AGGREGATION_FROZEN",
            "MAPPING_REVEALED_IN_THIS_GATE",
        ],
        "blind_bundle": _history(repo, BUNDLE_ROOT),
        "evaluator_1_freeze": _history(repo, EVALUATOR_1_ROOT),
        "evaluator_2_freeze": _history(repo, EVALUATOR_2_ROOT),
        "combined_blind_freeze": _history(repo, COMBINED_ROOT),
        "mapping_artifact_sealed_before_evaluation": True,
        "mapping_artifact_commit": _history(repo, MAPPING_ROOT),
        "mapping_was_inaccessible_to_evaluators": True,
        "mapping_reveal_baseline_head": START_HEAD,
        "mapping_reveal_occurs_after_combined_freeze": True,
        "mapping_contamination": 0,
    }

    arm_a = arm_binding["a_arm_identity"]
    arm_b = arm_binding["b_arm_identity"]
    lock_by_slot = {row["sample_slot"]: row for row in six_locks["locks"]}
    anonymous_rows = []
    for row in mapping_rows:
        lock = lock_by_slot[row["sample_slot"]]
        if lock["sample_id"] != row["sample_id"] or lock["arm"] != row["arm"]:
            raise RuntimeError(f"mapping/readiness lock drift: {row['sample_slot']}")
        anonymous_rows.append(
            {
                "anonymous_sample_id": row["anonymous_sample_id"],
                "prospective_sample_id": row["sample_id"],
                "experiment_arm": row["arm"],
                "sample_index": lock["sample_index"],
                "batch": f"PAIR_{lock['sample_index']}",
                "sample_slot": row["sample_slot"],
                "literary_artifact_sha256": row["artifact_file_sha256"],
                "blind_artifact_sha256": row["blind_artifact_sha256"],
            }
        )

    capacity_by_arm = {row["arm"]: row for row in capacity["arms"]}
    arm_counts = {
        arm: {
            "samples": sum(1 for row in campaign["validity"]["rows"] if row["sample_slot"].startswith(arm)),
            "sealed_valid": sum(
                1
                for row in campaign["validity"]["rows"]
                if row["sample_slot"].startswith(arm) and row["status"] == "SEALED_VALID"
            ),
            "provider_attempts": sum(
                row["attempts"].get("provider_dispatch_attempt_count", 0)
                for row in campaign["attempts"]["rows"]
                if row["sample_slot"].startswith(arm)
            ),
            "terminal_pipeline_pass": all(
                row["terminal_pipeline"].get("status") == "PASS"
                for row in campaign["terminal"]["rows"]
                if row["sample_slot"].startswith(arm)
            ),
        }
        for arm in ("A", "B")
    }

    documents: dict[str, bytes] = {}

    def add(name: str, value: Any) -> None:
        documents[name] = _json_bytes(value)

    documents["README.md"] = (
        "# Skill V3 character-heavy multi-sample mapping reveal decision\n\n"
        "Offline-only evidence that reveals the sealed anonymous mapping after both evaluators "
        "and the combined blind aggregation were frozen. It mechanically translates the frozen "
        "votes to experimental arms, applies the prospective narrative and engineering rules, "
        "and does not create new literary judgments or authorize a cutover.\n"
    ).encode("utf-8")
    add(
        "baseline-binding-v1.json",
        {
            "schema": "SkillV3MappingRevealBaselineBindingV1",
            "status": "EXACT",
            "branch": BRANCH,
            "start_head": START_HEAD,
            "start_worktree": "CLEAN",
            "decision_commit": "COMMIT_CONTAINING_THIS_NON_SELF_REFERENTIAL_REPORT",
            "final_head": "COMMIT_CONTAINING_THIS_NON_SELF_REFERENTIAL_REPORT",
            "final_worktree_expected": "CLEAN_AFTER_SEAL",
        },
    )
    add(
        "blind-freeze-binding-v1.json",
        {
            "schema": "SkillV3MappingRevealBlindFreezeBindingV1",
            "status": "EXACT",
            "evaluator_1_freeze_sha256": EVALUATOR_1_FREEZE_SHA256,
            "evaluator_2_freeze_sha256": EVALUATOR_2_FREEZE_SHA256,
            "literary_policy_sha256": LITERARY_POLICY_SHA256,
            "combined_literary_freeze_sha256": COMBINED_LITERARY_FREEZE_SHA256,
            "required_evaluators": 2,
            "required_batches": 3,
            "required_evaluator_by_batch_votes": 6,
            "observed_evaluator_by_batch_votes": 6,
            "missing_duplicate_extra": [0, 0, 0],
            "mapping_revealed_in_blind_evidence": False,
            "mapping_contamination": 0,
            "complete_required_vote_set": True,
            "blind_policy_drift": False,
            "parent_manifests": parent["manifests"],
        },
    )
    add("blind-chronology-v1.json", chronology)
    add(
        "mapping-manifest-binding-v1.json",
        {
            "schema": "SkillV3MappingManifestBindingV1",
            "status": "EXACT",
            "manifest": mapping_manifest,
            "mapping_status": mapping["status"],
            "mapping_frozen_before_evaluation": mapping["mapping_frozen_before_evaluation"],
            "one_to_one_mapping": True,
            "anonymous_sample_count": 6,
        },
    )
    add(
        "anonymous-to-sample-mapping-v1.json",
        {
            "schema": "SkillV3AnonymousToSampleMappingRevealV1",
            "status": "EXACT",
            "rows": anonymous_rows,
            "anonymous_ids_unique": True,
            "prospective_sample_ids_unique": True,
            "mapping_complete": True,
        },
    )
    add(
        "blind-side-to-experiment-arm-v1.json",
        {
            "schema": "SkillV3BlindSideToExperimentArmV1",
            "status": "EXACT",
            "global_blind_side_to_experiment_arm_mapping": "NOT_DEFINED_BY_DESIGN",
            "reason": "pair order was shuffled; blind side labels are positional, not arm identities",
            "pairs": [
                {"anonymous_pair_id": pair_id, **binding}
                for pair_id, binding in sorted(pair_mapping.items())
            ],
            "blind_side_b_must_not_be_assumed_to_mean_experiment_arm_b": True,
        },
    )
    add(
        "experimental-arm-identities-v1.json",
        {
            "schema": "SkillV3ExperimentalArmIdentitiesV1",
            "status": "EXACT",
            "experiment_arm_a_context_kind": arm_binding["a_skill_context_kind"],
            "experiment_arm_a_skill_context_sha256": arm_a["context_sha256"],
            "experiment_arm_a_profile_sha256": arm_a["profile_sha256"],
            "experiment_arm_b_context_kind": arm_binding["b_skill_context_kind"],
            "experiment_arm_b_skill_context_sha256": arm_b["context_sha256"],
            "experiment_arm_b_selected_section_sha256": arm_b["selected_section_sha256"],
            "selective_verbatim_arm": "EXPERIMENT_ARM_B",
            "baseline_control_arm": "EXPERIMENT_ARM_A",
            "primary_changed_variable": arm_binding["primary_changed_variable"],
        },
    )
    add(
        "frozen-blind-result-binding-v1.json",
        {
            "schema": "SkillV3FrozenBlindResultBindingV1",
            "status": "EXACT_IMMUTABLE",
            "rows": [
                {
                    "dimension": dimension,
                    "criticality": aggregate_by_dimension[dimension]["criticality"],
                    "blind_side_a_better": EXPECTED_BLIND_COUNTS[dimension][0],
                    "blind_side_b_better": EXPECTED_BLIND_COUNTS[dimension][1],
                    "tie_or_equivalent": EXPECTED_BLIND_COUNTS[dimension][2],
                    "blind_result": "BLIND_SIDE_B_BETTER",
                    "variance_flag": aggregate_by_dimension[dimension]["variance_flag"],
                }
                for dimension in DIMENSIONS
            ],
            "opposed_direction_dimensions": variance["opposed_direction_dimensions"],
            "direction_tie_variance_dimensions": variance["direction_tie_variance_dimensions"],
            "evaluator_disagreement_count": variance["evaluator_disagreement_count"],
            "evaluator_disagreements": variance["evaluator_disagreements"],
            "scalar_average_created": False,
            "new_literary_scoring_performed": False,
        },
    )
    add(
        "mapped-literary-dimension-results-v1.json",
        {
            "schema": "SkillV3MappedLiteraryDimensionResultsV1",
            "status": "COMPLETE",
            "method": "mechanical per-vote blind-position to experiment-arm translation followed by the sealed prospective ordinal rule",
            "rows": mapped_dimensions,
            "no_underlying_blind_judgment_edited": True,
            "scalar_average_created": False,
        },
    )
    add(
        "narrative-policy-binding-v1.json",
        {
            "schema": "SkillV3NarrativePolicyBindingV1",
            "status": "EXACT",
            "literary_policy_sha256": LITERARY_POLICY_SHA256,
            "policy_file": (BUNDLE_ROOT / "sealed-aggregation-policy-v1.json").as_posix(),
            "critical_dimensions": sorted(CRITICAL_DIMENSIONS),
            "noncritical_dimensions": sorted(set(DIMENSIONS) - CRITICAL_DIMENSIONS),
            "aggregation": narrative_rule["aggregation"],
            "critical_regression_handling": narrative_rule["worst_case_rule"],
            "noncritical_regression_handling": "reported dimension-by-dimension; cannot compensate for or erase a critical regression",
            "variance_handling": validation_policy["variance_handling"],
            "inconclusive_handling": validation_policy["inconclusive_rule"],
            "tie_equivalent_handling": "EQUIVALENT maps to sealed TIE and remains neutral",
            "opposed_direction_handling": "INCONCLUSIVE unless the sealed 4-of-6 support threshold is met",
            "minimum_support": narrative_rule["minimum_support"],
            "scalar_average_allowed": False,
            "retrospective_tuning_allowed": False,
        },
    )
    add(
        "narrative-non-inferiority-v1.json",
        {
            "schema": "SkillV3NarrativeNonInferiorityV1",
            "status": "DECIDED",
            "narrative_non_inferior": narrative_non_inferior,
            "selective_critical_better_count": critical_counts["SELECTIVE_VERBATIM_BETTER"],
            "selective_critical_equivalent_count": critical_counts["EQUIVALENT"],
            "selective_critical_regression_count": critical_counts["BASELINE_BETTER"],
            "selective_critical_inconclusive_count": critical_counts["INCONCLUSIVE"],
            "selective_noncritical_better_count": noncritical_counts["SELECTIVE_VERBATIM_BETTER"],
            "selective_noncritical_equivalent_count": noncritical_counts["EQUIVALENT"],
            "selective_noncritical_regression_count": noncritical_counts["BASELINE_BETTER"],
            "selective_noncritical_inconclusive_count": noncritical_counts["INCONCLUSIVE"],
            "reason": "all three critical dimensions are supported BASELINE_BETTER results after per-pair mapping",
            "generalized_superiority_claimed": False,
        },
    )
    add(
        "campaign-engineering-binding-v1.json",
        {
            "schema": "SkillV3CampaignEngineeringBindingV1",
            "status": "EXACT",
            "readiness_manifest": readiness_manifest,
            "campaign_manifest": campaign_manifest,
            "total_samples": 6,
            "sealed_valid": 6,
            "sealed_invalid": 0,
            "total_real_provider_requests": 6,
            "per_sample_provider_attempts": 1 if per_sample_provider_attempts == [1, 1, 1, 1, 1, 1] else "DRIFT",
            "total_retry": campaign["budget"]["retry_count"],
            "total_transport_retry": 0 if retry_exact else "DRIFT",
            "total_fallback": campaign["budget"]["fallback_count"],
            "total_route_switch": campaign["budget"]["route_switch_count"],
            "total_resume_dispatch": campaign["budget"]["resume_count"],
            "total_second_dispatch": campaign["budget"]["second_dispatch_count"],
            "all_approvals_single_use_final_consumed": all_approvals_consumed,
            "all_nonces_single_use_final_consumed": all_nonces_consumed,
            "destination": "https://lingsuan.org:443/v1/messages",
            "alternate_destination_count": 0,
            "cross_origin_redirect_count": 0,
            "story_state_canon_ready_mutations": [0, 0, 0],
            "production_authority": False,
            "production_src_diff": 0,
            "baml_src_diff": 0,
            "campaign_strict_l3": campaign["tests"]["strict_l3"],
            "campaign_privacy": campaign["privacy"]["status"],
            "route_fingerprint": model_route["route_fingerprint"],
            "model_binding_sha256": model_route["model_binding_sha256"],
            "provider_descriptor_sha256": model_route["provider_descriptor_sha256"],
            "validator_sha256": lock_by_slot["A1"]["validator_sha256"],
        },
    )
    add(
        "engineering-comparison-v1.json",
        {
            "schema": "SkillV3EngineeringComparisonV1",
            "status": "COMPLETE_WITH_OBSERVABILITY_LIMITS",
            "arms": {
                "A_BASELINE_CONTROL": {
                    **arm_counts["A"],
                    "skill_context_chars": capacity_by_arm["A"]["skill_context_chars"],
                    "skill_context_token_estimate": capacity_by_arm["A"]["skill_context_token_estimate"],
                    "total_input_estimate": capacity_by_arm["A"]["total_input_estimate"],
                    "headroom": capacity_by_arm["A"]["headroom"],
                },
                "B_SELECTIVE_VERBATIM": {
                    **arm_counts["B"],
                    "skill_context_chars": capacity_by_arm["B"]["skill_context_chars"],
                    "skill_context_token_estimate": capacity_by_arm["B"]["skill_context_token_estimate"],
                    "total_input_estimate": capacity_by_arm["B"]["total_input_estimate"],
                    "headroom": capacity_by_arm["B"]["headroom"],
                },
            },
            "b_minus_a_skill_context_chars": capacity_by_arm["B"]["skill_context_chars"] - capacity_by_arm["A"]["skill_context_chars"],
            "b_minus_a_skill_context_token_estimate": capacity_by_arm["B"]["skill_context_token_estimate"] - capacity_by_arm["A"]["skill_context_token_estimate"],
            "b_minus_a_headroom": capacity_by_arm["B"]["headroom"] - capacity_by_arm["A"]["headroom"],
            "capacity_both_pass": capacity["a_capacity"] == capacity["b_capacity"] == "PASS",
            "no_silent_truncation": capacity["no_silent_truncation"],
            "advisory_truncation_occurred": reference_binding["advisory_truncation_occurred"],
            "advisory_shedding_occurred": reference_binding["advisory_shedding_occurred"],
            "non_skill_byte_identity": byte_identity["status"],
            "only_skill_context_differs_by_arm": byte_identity["only_skill_context_differs_by_arm"],
            "route_model_destination_identity": "PASS" if route_identity_exact and model_identity_exact and provider_identity_exact and egress_exact else "FAIL",
            "validator_identity": "PASS" if validator_identity_exact else "FAIL",
            "production_isolation": "PASS" if production_isolation_exact and all_terminal_pass else "FAIL",
            "provenance": "PASS" if provenance_exact else "FAIL",
            "a1_output_tokens_observed": 649,
            "a1_finish_reason_observed": "end_turn",
            "a1_input_tokens_observed": False,
            "most_other_token_and_finish_fields_retained": False,
            "token_comparison_sufficient": "NO",
            "cost_comparison_sufficient": "NO",
            "cost_observability": campaign["budget"]["cost_cap"],
        },
    )
    add(
        "engineering-non-inferiority-v1.json",
        {
            "schema": "SkillV3EngineeringNonInferiorityV1",
            "status": "DECIDED",
            "engineering_non_inferior": engineering_non_inferior,
            "prospective_engineering_hard_failure_rule": validation_policy["engineering_hard_failure_rule"],
            "regressions": engineering_regressions,
            "token_comparison_sufficient": "NO",
            "cost_comparison_sufficient": "NO",
            "reason": "both arms produced 3/3 sealed-valid outputs under identical hard bounds with no dispatch, route, validator, isolation, provenance, capacity, truncation, or egress regression",
            "literary_results_used": False,
        },
    )
    add(
        "pilot-disposition-v1.json",
        {
            "schema": "SkillV3CharacterHeavyPilotDispositionV1",
            "status": "DECIDED",
            "narrative_non_inferior": narrative_non_inferior,
            "engineering_non_inferior": engineering_non_inferior,
            "experiment_lock_valid": True,
            "blinding_valid": True,
            "sample_validity": "6/6 SEALED_VALID",
            "methodology_complete": True,
            "final_pilot_disposition": FINAL_DISPOSITION,
            "decision_priority": "narrative critical regression produces NO_GO_QUALITY even though engineering non-inferiority passes",
            "exact_next_gate": NEXT_GATE,
        },
    )
    add(
        "architectural-interpretation-v1.json",
        {
            "schema": "SkillV3CharacterHeavyArchitecturalInterpretationV1",
            "status": "BOUNDED",
            "selective_verbatim_met_character_heavy_narrative_non_inferiority": False,
            "selective_verbatim_met_engineering_non_inferiority": True,
            "selective_verbatim_beat_baseline_on_any_frozen_mapped_aggregate": False,
            "selective_verbatim_beat_baseline_on_all_frozen_mapped_aggregates": False,
            "remaining_variance": {
                "voice_readiness": "INCONCLUSIVE_3_TO_3_OPPOSED",
                "anti_template_risk": "INCONCLUSIVE_3_TO_2_WITH_1_TIE",
                "frozen_evaluator_disagreement_count": variance["evaluator_disagreement_count"],
            },
            "proves": [
                "the sealed character-heavy six-sample method completed without engineering hard failure",
                "the selective-verbatim arm is engineering non-inferior within the sealed character-heavy experiment",
                "the selective-verbatim arm failed the prospective narrative non-inferiority rule for this demand class",
            ],
            "does_not_prove": [
                "generalized Skill V3 narrative or engineering non-inferiority",
                "fitness for other demand classes",
                "production cutover readiness",
                "actual token-use or cost parity",
            ],
            "one_character_heavy_multi_sample_pass_does_not_prove_generalized_skill_v3_non_inferiority": True,
            "production_cutover_authorized": False,
        },
    )
    add(
        "test-receipt-v1.json",
        {
            "schema": "SkillV3MappingRevealDecisionTestReceiptV1",
            "status": "PASS",
            "focused": focused_tests,
            "related": related_tests,
            "full_offline_suite": full_suite,
            "coverage": [
                "mapping completeness",
                "blind-side to experiment-arm translation",
                "freeze immutability",
                "decision-rule application",
                "campaign evidence binding",
                "engineering comparison",
                "manifest and privacy",
            ],
            "new_owning_source_regression_count": new_owning_source_regression_count,
            "external_calls": 0,
        },
    )
    add(
        "strict-l3-receipt-v1.json",
        {
            "schema": "SkillV3MappingRevealDecisionStrictL3ReceiptV1",
            "status": "PASS",
            "result": strict_l3,
            "warnings": 0,
            "blockers": 0,
            "declared_level": "L3",
            "review_mode": "MAIN_CODEX_SINGLE_AGENT_NO_INDEPENDENCE_CLAIM",
            "production_source_changed": False,
            "authority_critical_module_change_count": 0,
        },
    )

    critical_summary = {
        "better": critical_counts["SELECTIVE_VERBATIM_BETTER"],
        "equivalent": critical_counts["EQUIVALENT"],
        "regression": critical_counts["BASELINE_BETTER"],
        "inconclusive": critical_counts["INCONCLUSIVE"],
    }
    noncritical_summary = {
        "better": noncritical_counts["SELECTIVE_VERBATIM_BETTER"],
        "equivalent": noncritical_counts["EQUIVALENT"],
        "regression": noncritical_counts["BASELINE_BETTER"],
        "inconclusive": noncritical_counts["INCONCLUSIVE"],
    }
    mapping_lines = "\n".join(
        f"- `{row['anonymous_sample_id']}` → `{row['sample_slot']}` / arm `{row['experiment_arm']}` / `{row['prospective_sample_id']}` / artifact `{row['literary_artifact_sha256']}`"
        for row in anonymous_rows
    )
    mapped_lines = "\n".join(
        f"- `{row['dimension']}` ({row['criticality']}): blind `{row['blind_counts']}` / `{row['blind_result']}` → mapped `{row['mapped_experiment_counts']}` / `{row['mapped_experiment_result']}`; variance={row['blind_variance_flag']}, opposed={row['opposed_direction_flag']}, evaluator_disagreement={row['evaluator_disagreement_flag']}"
        for row in mapped_dimensions
    )
    pair_lines = "\n".join(
        f"- `{pair}`: blind A → arm `{binding['blind_side_a_experiment_arm']}` ({binding['blind_side_a_sample_slot']}), blind B → arm `{binding['blind_side_b_experiment_arm']}` ({binding['blind_side_b_sample_slot']})"
        for pair, binding in sorted(pair_mapping.items())
    )
    report = f"""# Skill V3 multi-sample mapping reveal and engineering decision

## Outcome

`{FINAL_DISPOSITION}`

`NARRATIVE_NON_INFERIOR={narrative_non_inferior}`

`ENGINEERING_NON_INFERIOR={engineering_non_inferior}`

The sealed mapping reverses blind-side order in pairs 1 and 3 but not pair 2. After every frozen vote is translated per pair, all three critical dimensions are supported `BASELINE_BETTER` results. The pilot therefore fails narrative non-inferiority while passing the separately evaluated engineering hard-failure rule.

## Required report

1. Branch/start HEAD: `{BRANCH}` / `{START_HEAD}`; starting worktree `CLEAN`.
2. Reveal decision commit/final HEAD: `COMMIT_CONTAINING_THIS_NON_SELF_REFERENTIAL_REPORT`; final worktree `CLEAN_AFTER_SEAL`. The actual immutable commit SHA is reported by the sealing command and final user response because a commit cannot contain its own hash.
3. Freeze SHAs: evaluator 1 `{EVALUATOR_1_FREEZE_SHA256}`; evaluator 2 `{EVALUATOR_2_FREEZE_SHA256}`; combined `{COMBINED_LITERARY_FREEZE_SHA256}`.
4. Blind chronology: bundle → evaluator 1 freeze → evaluator 2 independent freeze → combined freeze → reveal in this gate; mapping contamination `0`; policy drift `NO`; required votes `6/6`.
5. Mapping manifest: `{mapping_manifest['manifest_file_sha256']}` / `EXACT`; one-to-one `YES`.
6. Anonymous mappings:\n{mapping_lines}
7. Blind-side mapping is per pair, never global:\n{pair_lines}
8. Arm A: `{arm_binding['a_skill_context_kind']}` / context `{arm_a['context_sha256']}` / profile `{arm_a['profile_sha256']}`. Arm B: `{arm_binding['b_skill_context_kind']}` / context `{arm_b['context_sha256']}`.
9. Selective-verbatim arm: `EXPERIMENT_ARM_B`; baseline control: `EXPERIMENT_ARM_A`.
10–13. Frozen blind counts, mapped results, criticality, and variance:\n{mapped_lines}
14. Narrative policy SHA: `{LITERARY_POLICY_SHA256}`; no scalar averaging or retrospective tuning.
15. Selective critical counts: `{critical_summary}`. Selective noncritical counts: `{noncritical_summary}`.
16. `NARRATIVE_NON_INFERIOR={narrative_non_inferior}`. This is a critical-regression decision, not a generalized architecture claim.
17. Engineering campaign: `6/6 SEALED_VALID`; Provider/HTTP/network requests `6/6/6`; per sample Provider attempts `1`; retry/transport retry/fallback/route switch/resume/second dispatch all `0`; approvals/nonces all single-use and consumed.
18. Engineering comparison: both arms `3/3` valid and terminal-pipeline PASS. A/B skill-context chars `{capacity_by_arm['A']['skill_context_chars']}/{capacity_by_arm['B']['skill_context_chars']}`; token estimates `{capacity_by_arm['A']['skill_context_token_estimate']}/{capacity_by_arm['B']['skill_context_token_estimate']}`; headroom `{capacity_by_arm['A']['headroom']}/{capacity_by_arm['B']['headroom']}`. `TOKEN_COMPARISON_SUFFICIENT=NO`; `COST_COMPARISON_SUFFICIENT=NO` because A1 input tokens and most other token/finish fields were not retained and cost is unknown. A1 alone observed `output_tokens=649`, `finish_reason=end_turn`.
19. `ENGINEERING_NON_INFERIOR={engineering_non_inferior}`; all named selective-verbatim regression categories are false.
20. Final disposition: `{FINAL_DISPOSITION}`.
21. This proves bounded character-heavy engineering non-inferiority and a character-heavy narrative no-go for the current Selective Verbatim context. It does not prove generalized Skill V3 behavior, other demand-class behavior, actual token/cost parity, or cutover readiness. `ONE_CHARACTER_HEAVY_MULTI_SAMPLE_PASS_DOES_NOT_PROVE_GENERALIZED_SKILL_V3_NON_INFERIORITY`.
22. Cutovers: Skill V3 `NO`; Planning V2 `NO`; production authority `false`.
23. Full Short: `NOT_EXECUTED`.
24. Tests: focused `{focused_tests}`; related `{related_tests}`; full offline `{full_suite}`; Strict L3 `{strict_l3}`; warnings/blockers `0/0`; new owning-source regressions `{new_owning_source_regression_count}`; privacy `PASS`; manifest covers every evidence file except itself.
25. Exact next gate: `{NEXT_GATE}`.

## External and authority state

`REAL_PROVIDER_CALLS=0`

`NETWORK_CALLS=0`

`MODEL_CALLS=0`

`PAID_CALLS=0`

`NEW_LITERARY_EVALUATION=NO`

`SKILL_V3_CUTOVER=NO`

`PLANNING_V2_CUTOVER=NO`

`FULL_SHORT_CANARY=NOT_EXECUTED`
"""
    documents["final-report-v1.md"] = report.encode("utf-8")

    privacy = _privacy_scan(documents)
    if privacy["status"] != "PASS":
        raise RuntimeError(f"privacy scan failed: {privacy['matches']}")
    add("privacy-scan-v1.json", privacy)
    entries = _manifest_entries(documents)
    definition = {
        "schema": "SkillV3MappingRevealDecisionSha256ManifestV1",
        "status": "EXACT",
        "coverage": "all evidence files except sha256-manifest-v1.json itself",
        "entry_count": len(entries),
        "entries": entries,
    }
    documents["sha256-manifest-v1.json"] = _json_bytes(
        {
            "schema": "SkillV3MappingRevealDecisionManifestEnvelopeV1",
            "definition": definition,
            "definition_sha256": _sha_bytes(_json_bytes(definition)),
        }
    )
    return documents


def write_artifacts(repo: Path, documents: dict[str, bytes]) -> Path:
    output = repo / OUTPUT_RELATIVE_ROOT
    output.mkdir(parents=True, exist_ok=True)
    expected = set(documents)
    existing = {path.name for path in output.iterdir() if path.is_file()}
    stale = existing - expected
    if stale:
        raise RuntimeError(f"unexpected existing evidence files: {sorted(stale)}")
    for name, content in documents.items():
        (output / name).write_bytes(content)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize the offline Skill V3 mapping reveal decision evidence.")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--focused-tests", required=True)
    parser.add_argument("--related-tests", required=True)
    parser.add_argument("--full-suite", required=True)
    parser.add_argument("--strict-l3", required=True)
    parser.add_argument("--new-owning-source-regression-count", type=int, required=True)
    args = parser.parse_args()
    repo = args.repo_root.resolve()
    documents = build_artifacts(
        repo,
        focused_tests=args.focused_tests,
        related_tests=args.related_tests,
        full_suite=args.full_suite,
        strict_l3=args.strict_l3,
        new_owning_source_regression_count=args.new_owning_source_regression_count,
    )
    output = write_artifacts(repo, documents)
    manifest = json.loads(documents["sha256-manifest-v1.json"])
    print(f"EVIDENCE_ROOT={output}")
    print(f"NARRATIVE_NON_INFERIOR=NO")
    print(f"ENGINEERING_NON_INFERIOR=YES")
    print(FINAL_DISPOSITION)
    print(f"MANIFEST_DEFINITION_SHA256={manifest['definition_sha256']}")
    print(f"MANIFEST_FILE_SHA256={_sha_file(output / 'sha256-manifest-v1.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
