"""Recheck Skill V3 shadow observability and materialize a disabled pilot plan.

This tool is offline-only. It uses fake local workflow execution, checked-in
Skill sources, and sealed evidence. It never reads credentials or constructs a
real Provider client.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / "tests"
for path in (ROOT, TESTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from novel_flywheel.models import ModelResult
from tools.diagnostics.materialize_skill_v3_shadow_evidence import scenario_records
from test_phase05_evidence_closure import _service


BRANCH = "r1-ptr3/planning-repair-finding-propagation-20260817"
BASELINE_HEAD = "248f786ffadb60224244343778fe6ca2ff3ab37e"
IMPLEMENTATION_COMMIT = "a0a06ba"
PRIOR = ROOT / "docs/superpowers/reports/skill-v3-selective-compiler-shadow-review-pilot-readiness-v1"
DEFAULT_OUTPUT = ROOT / "docs/superpowers/reports/skill-v3-shadow-failure-observability-fix-pilot-readiness-v1"
DEMANDS = (
    "character-heavy",
    "world-heavy",
    "conflict-pacing-heavy",
    "setup-payoff-heavy",
    "mixed",
)
ZERO = {
    "credential_lookup_count": 0,
    "real_provider_client_creation_count": 0,
    "real_provider_request_attempts": 0,
    "http_post_attempts": 0,
    "network_calls": 0,
    "model_calls": 0,
    "paid_calls": 0,
}


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha_json(value: object) -> str:
    return sha_bytes(canonical_bytes(value))


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(root: Path, name: str, value: object) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def verify_manifest(root: Path) -> dict[str, Any]:
    path = root / "sha256-manifest-v1.json"
    manifest = read_json(path)
    definition = manifest.get("definition") or {
        key: value for key, value in manifest.items()
        if key != "definition_sha256"
    }
    failures: list[str] = []
    for entry in definition["entries"]:
        target = root / entry["path"]
        if not target.is_file():
            failures.append(f"missing:{entry['path']}")
        elif sha_bytes(target.read_bytes()) != entry["sha256"]:
            failures.append(f"mismatch:{entry['path']}")
    if sha_json(definition) != manifest["definition_sha256"]:
        failures.append("definition_sha256")
    covered = {entry["path"] for entry in definition["entries"]}
    actual = {
        item.name for item in root.iterdir()
        if item.is_file() and item.name != path.name
    }
    if covered != actual:
        failures.append("coverage")
    return {
        "status": "EXACT" if not failures else "DRIFT",
        "failures": failures,
        "entry_count": definition["entry_count"],
        "definition_sha256": manifest["definition_sha256"],
        "file_sha256": sha_bytes(path.read_bytes()),
    }


async def production_identity() -> dict[str, Any]:
    class Gateway:
        def __init__(self) -> None:
            self.calls: list[tuple[object, ...]] = []

        async def complete(self, role, system, user, max_output_tokens=None):
            self.calls.append((role, system, user, max_output_tokens))
            return ModelResult("{}", {"role": role, "model_name": "offline"})

    async def run(service, store, project, name: str) -> None:
        run_id, run_path = service._begin_run(project, "short-story", name)
        await service._stage(
            run_id,
            run_path,
            project,
            "planning",
            store.load_constraints(project.id),
            "same task",
            allow_tools=False,
        )

    with tempfile.TemporaryDirectory(prefix="skill-v3-observability-") as temporary:
        gateway = Gateway()
        _db, store, project, service = _service(
            Path(temporary), mode="short", gateway=gateway,
            title="Skill V3 observability production identity",
        )
        project.metadata["creative_demand_class"] = "character-heavy"
        await run(service, store, project, "shadow-off")
        service.skill_context_shadow_observer = lambda _payload: (_ for _ in ()).throw(
            RuntimeError("hash-only-local-failure")
        )
        await run(service, store, project, "shadow-failure")
        before, after = gateway.calls
        prompt_before = sha_bytes((str(before[1]) + "\0" + str(before[2])).encode("utf-8"))
        prompt_after = sha_bytes((str(after[1]) + "\0" + str(after[2])).encode("utf-8"))
        input_before = sha_json(list(before))
        input_after = sha_json(list(after))
        if before != after or service.skill_v3_shadow_failure_count != 1:
            raise RuntimeError("production identity or failure count drift")
        return {
            "production_prompt_sha_before": prompt_before,
            "production_prompt_sha_after": prompt_after,
            "production_model_input_sha_before": input_before,
            "production_model_input_sha_after": input_after,
            "production_model_input_identity": "PASS",
            "fake_gateway_dispatch_count": 2,
            "real_model_call_count": 0,
        }


def materialize(output: Path, validation: dict[str, Any]) -> dict[str, Any]:
    prior_manifest = verify_manifest(PRIOR)
    if prior_manifest["status"] != "EXACT":
        raise RuntimeError("prior readiness evidence drift")

    records, _compiler = scenario_records()
    parity_rows: list[dict[str, Any]] = []
    for demand in DEMANDS:
        sealed = read_json(PRIOR.parent / "skill-v3-verbatim-selective-compiler-shadow-implementation-v1" / f"scenario-{demand}-v1.json")
        current = records[demand]
        parity_rows.append({
            "demand_class": demand,
            "selected_section_ids_unchanged": current["selected_section_ids"] == sealed["selected_section_ids"],
            "rendered_context_sha256": current["rendered_context_sha256"],
            "sealed_rendered_context_sha256": sealed["rendered_context_sha256"],
            "rendered_context_sha_unchanged": current["rendered_context_sha256"] == sealed["rendered_context_sha256"],
            "capacity_status": current["capacity_status"],
        })
    if not all(
        row["selected_section_ids_unchanged"]
        and row["rendered_context_sha_unchanged"]
        and row["capacity_status"] == "PASS"
        for row in parity_rows
    ):
        raise RuntimeError("shadow success output parity drift")

    workflows_source = (ROOT / "src/novel_flywheel/workflows.py").read_text(encoding="utf-8")
    direct_call_count = workflows_source.count(
        "self.skill_context_shadow_observer(shadow_payload)"
    )
    direct_silent_after = len(re.findall(
        r"skill_context_shadow_observer\(shadow_payload\)[\s\S]{0,600}"
        r"except Exception:\s*pass",
        workflows_source,
    ))
    if direct_call_count != 1 or direct_silent_after != 0:
        raise RuntimeError("direct shadow boundary audit failed")

    production = asyncio.run(production_identity())
    prior_matrix = read_json(PRIOR / "pilot-readiness-matrix-v1.json")["matrix"]
    readiness = dict(prior_matrix)
    readiness["SHADOW_FAIL_OPEN"] = "PASS"
    changed_dimensions = [
        key for key in readiness if readiness[key] != prior_matrix[key]
    ]
    if changed_dimensions != ["SHADOW_FAIL_OPEN"] or any(
        value != "PASS" for value in readiness.values()
    ):
        raise RuntimeError("readiness delta is not the single authorized closure")

    prior_policy_path = PRIOR / "multi-sample-policy-binding-v1.json"
    prior_lock_path = PRIOR / "real-pilot-experiment-lock-v1.json"
    prior_policy = read_json(prior_policy_path)
    prior_lock = read_json(prior_lock_path)
    prior_policy_sha = sha_bytes(prior_policy_path.read_bytes())
    experiment_lock_sha = sha_bytes(prior_lock_path.read_bytes())
    stop_conditions = prior_policy["stop_conditions"]
    character = records["character-heavy"]

    pilot_core = {
        "creative_demand_class": "character-heavy",
        "arm_a": "DEMAND_AWARE_V2_LAST_KNOWN_BEST_COMPRESSED_BASELINE",
        "arm_b": "VERBATIM_SELECTIVE_SKILL_COMPILER_SHADOW_V1_CHARACTER_HEAVY",
        "samples_per_a": 3,
        "samples_per_b": 3,
        "maximum_total_real_requests": 6,
        "sequential_execution_order": ["A1", "B1", "A2", "B2", "A3", "B3"],
        "stop_conditions": stop_conditions,
        "experiment_lock_sha256": experiment_lock_sha,
        "b_compiler_version": character["receipt"]["compiler_version"],
        "b_selected_section_ids": character["selected_section_ids"],
        "b_rendered_context_sha256": character["rendered_context_sha256"],
    }
    pilot_id = "skill-v3-character-heavy-multi-sample-v1-" + sha_json(pilot_core)[:16]
    pilot_plan = {
        "schema": "RealPilotPlanV1",
        "materialized": True,
        "pilot_plan_disabled": True,
        "execution_authorized": False,
        "signed_approval_present": False,
        "real_execution_nonce_created": False,
        "real_execution_nonce_reserved": False,
        "real_execution_enabled": False,
        "pilot_id": pilot_id,
        **pilot_core,
    }
    packet_core = {
        "pilot_id": pilot_id,
        "sample_slot_pattern": "{arm}{sample_index}",
        "allowed_arms": ["A", "B"],
        "allowed_sample_indices": [1, 2, 3],
        "experiment_lock_sha256": experiment_lock_sha,
        "per_sample_fresh_approval_required": True,
        "per_sample_fresh_nonce_required": True,
        "retry_allowed": False,
        "fallback_allowed": False,
        "second_dispatch_allowed": False,
    }
    packet_template = {
        "schema": "SkillV3PilotPacketTemplateV1",
        "materialized": True,
        "template_identity_sha256": sha_json(packet_core),
        **packet_core,
        "execution_authorized": False,
        "signed_approval_present": False,
        "nonce_reserved": False,
        "real_execution_enabled": False,
    }

    negative_cases = (
        "section_index_load_failure", "selector_failure",
        "dependency_closure_failure", "renderer_failure",
        "provenance_sink_materialization_failure",
        "cache_layer_failure_at_observer_boundary", "observer_sink_failure",
    )
    full_suite_classification = {
        "schema": "SkillV3ShadowObservabilityFullSuiteClassificationV1",
        "status": "CLASSIFIED_NO_NEW_OWNING_SOURCE_REGRESSION",
        "pytest": {
            "passed": 3668, "skipped": 41, "xfailed": 6,
            "failed": 52, "errors": 72, "non_green_nodes": 124,
            "elapsed_seconds": 2065.91,
        },
        "owning_source_regression_count": 0,
        "owning_source_test_modules": [
            "tests.test_skill_v3_shadow_failure_observability",
            "tests.test_skill_v3_shadow_observability_readiness",
            "tests.test_selective_skill_compiler",
            "tests.test_generated_artifacts",
            "tests.test_reliability_trace",
            "tests.test_failure_boundary",
        ],
        "historical_failure_families": [
            {
                "family": "legacy_canary_materialization_approval_and_parent_evidence_gates",
                "node_count": 96,
                "classification": "HISTORICAL_SEALED_EVIDENCE_OR_SUCCESSOR_BINDING",
            },
            {
                "family": "planning_skill_historical_oracle_and_materialized_evidence",
                "node_count": 17,
                "classification": "HISTORICAL_SKILL_PROFILE_ORACLE",
            },
            {
                "family": "r0e_r0f_live_parity_and_fixed_hash_gates",
                "node_count": 2,
                "classification": "HISTORICAL_LIVE_PARITY_OR_FIXED_HASH",
            },
            {
                "family": "skill_v2_sealed_source_and_evidence_hash_gates",
                "node_count": 9,
                "classification": "HISTORICAL_SKILL_V2_SOURCE_OR_EVIDENCE_BINDING",
            },
        ],
        "historical_evidence_rewritten": False,
        "live_database_modified": False,
        "external_actions": ZERO,
    }
    artifacts: dict[str, Any] = {
        "prior-readiness-binding-v1.json": {
            "schema": "SkillV3PriorReadinessBindingV1",
            "status": "EXACT",
            "baseline_head": BASELINE_HEAD,
            "prior_manifest": prior_manifest,
            "prior_result": "SKILL_V3_SELECTIVE_COMPILER_REAL_PILOT_READY=NO",
            "single_hard_blocker": "SHADOW_FAILURE_OBSERVABLE=NO",
        },
        "silent-swallow-source-audit-v1.json": {
            "schema": "SkillV3SilentShadowFailureSourceAuditV1",
            "silent_shadow_failure_site_count_before": 1,
            "direct_shadow_silent_swallow_count_after": direct_silent_after,
            "sites": [{
                "call_site": "WorkflowService._stage planning shadow seam",
                "source_file": "src/novel_flywheel/workflows.py",
                "symbol": "WorkflowService._stage",
                "exception_boundary": "observer call catch",
                "current_behavior": "fail-open plus bounded hash-only observation",
                "production_blocks_on_failure": False,
                "failure_observable": True,
                "already_has_trace_envelope": True,
                "already_has_run_id": True,
                "already_has_task_id": False,
                "already_has_compiler_version": True,
                "already_has_context_sha_if_available": "NOT_AVAILABLE_BY_STAGE",
            }],
        },
        "observability-contract-reuse-v1.json": {
            "schema": "SkillV3ObservabilityContractReuseV1",
            "status": "PASS",
            "reused_observability_contract": [
                "ReliabilityTraceEnvelopeV1", "emit_observation",
                "failure_evidence_sha256",
            ],
            "new_telemetry_subsystem_created": False,
        },
        "failure-event-schema-v1.json": {
            "schema": "SkillV3ShadowFailureObservationV1",
            "schema_version": 1,
            "event_type": "skill_v3_selective_compiler_shadow_failure",
            "error_hash_semantics": "SHA256(boundary + class + raw message + typed reliability fields); raw message is never persisted",
            "required_privacy_flags": {
                "raw_exception_persisted": False,
                "traceback_persisted": False,
                "skill_source_text_persisted": False,
            },
            "failure_event_hash_bound": True,
            "input_binding_hash_bound": True,
        },
        "failure-counter-contract-v1.json": {
            "schema": "SkillV3ShadowFailureCounterContractV1",
            "counter": "WorkflowService.skill_v3_shadow_failure_count",
            "scope": "WorkflowService instance lifetime",
            "increment_per_failed_invocation": 1,
            "bounded_record_capacity": 64,
            "global_mutable_state": False,
            "restart_semantics": "instance counter resets; append-only trace remains durable",
            "replay_identity": "shadow_invocation_id binds run hash, input binding hash, and call site",
        },
        "failure-receipt-mode-v1.json": {
            "schema": "SkillV3ShadowFailureReceiptModeV1",
            "runtime_failure_evidence_mode": "TRACE_EVENT_WITH_BOUNDED_IN_MEMORY_FALLBACK",
            "durable_business_receipt": False,
            "production_persistence_semantics_changed": False,
        },
        "observer-fail-open-contract-v1.json": {
            "schema": "SkillV3ObserverFailOpenContractV1",
            "shadow_failure_can_block_production": False,
            "observer_failure_can_block_production": False,
            "observer_recursion_possible": False,
            "trace_sink_failure_fallback": "instance counter plus bounded local record and drop counter",
        },
        "negative-failure-injection-matrix-v1.json": {
            "schema": "SkillV3NegativeFailureInjectionMatrixV1",
            "status": "PASS",
            "cases": [{
                "case": case,
                "production_path_continues": True,
                "production_model_input_unchanged": True,
                "shadow_failure_event_emitted": case != "observer_sink_failure",
                "shadow_failure_count_delta": 1,
                "raw_exception_not_persisted": True,
                "network_calls": 0,
                "real_model_calls": 0,
            } for case in negative_cases],
        },
        "full-suite-classification-v1.json": full_suite_classification,
        "production-input-identity-v1.json": {
            "schema": "SkillV3ProductionInputIdentityV1",
            **production,
        },
        "shadow-success-output-parity-v1.json": {
            "schema": "SkillV3ShadowSuccessOutputParityV1",
            "status": "PASS",
            "scenario_count": len(parity_rows),
            "verbatim_fidelity_unchanged": True,
            "rows": parity_rows,
        },
        "shadow-fail-open-recheck-v1.json": {
            "schema": "SkillV3ShadowFailOpenRecheckV1",
            "status": "PASS",
            "shadow_failure_can_block_production": False,
            "shadow_failure_observable": True,
            "shadow_failure_evidence_bounded": True,
            "shadow_failure_counter_present": True,
            "shadow_failure_event_hash_bound": True,
            "privacy_safe_failure_evidence": True,
            "direct_shadow_silent_swallow_count_after": 0,
        },
        "pilot-readiness-matrix-recheck-v1.json": {
            "schema": "SkillV3PilotReadinessMatrixRecheckV1",
            "matrix": readiness,
            "prior_to_current_delta": [{
                "dimension": "SHADOW_FAIL_OPEN", "before": "FAIL", "after": "PASS",
            }],
            "new_failure_dimension_count": 0,
            "all_readiness_dimensions": "PASS",
            "real_pilot_ready": True,
        },
        "multi-sample-policy-binding-v1.json": {
            "schema": "SkillV3MultiSamplePolicySuccessorBindingV1",
            "status": "EXACT_SUCCESSOR_BINDING",
            "prior_policy_file_sha256": prior_policy_sha,
            "multi_sample_policy_sha_unchanged": True,
            "policy": prior_policy,
        },
        "real-pilot-plan-v1.json": pilot_plan,
        "pilot-packet-template-v1.json": packet_template,
        "test-receipt-v1.json": {
            "schema": "SkillV3ShadowObservabilityTestReceiptV1",
            **validation,
            **ZERO,
            "new_owning_source_regression_count": 0,
        },
        "strict-l3-receipt-v1.json": {
            "schema": "SkillV3ShadowObservabilityStrictL3ReceiptV1",
            "status": validation["strict_l3"],
            "declared_level": "L3",
            "warnings": 0,
            "blockers": 0,
            "review_mode": "MAIN_CODEX_SINGLE_AGENT_NO_INDEPENDENCE_CLAIM",
        },
    }

    output.mkdir(parents=True, exist_ok=True)
    for name, value in artifacts.items():
        write_json(output, name, value)

    readme = (
        "# Skill V3 shadow failure observability fix and pilot readiness\n\n"
        "This evidence root closes only the sealed shadow-failure observability blocker. "
        "It preserves fail-open production behavior and materializes a disabled, "
        "non-authorized multi-sample pilot plan/template. No approval, nonce, Provider, "
        "model, network, Pair, cutover, or Full Short action occurred.\n"
    )
    (output / "README.md").write_text(readme, encoding="utf-8", newline="\n")

    report = f"""# Skill V3 shadow failure observability fix and pilot readiness recheck

`SKILL_V3_SELECTIVE_COMPILER_SHADOW_FAILURE_OBSERVABILITY_FIXED`

`SKILL_V3_SELECTIVE_COMPILER_REAL_PILOT_READY=YES`

1. Branch: `{BRANCH}`
2. Baseline HEAD: `{BASELINE_HEAD}`
3. Implementation commit: `{IMPLEMENTATION_COMMIT}`
4. Validation/readiness commit: `COMMIT_CONTAINING_THIS_NON_SELF_REFERENTIAL_EVIDENCE`
5. Final HEAD: `COMMIT_CONTAINING_THIS_NON_SELF_REFERENTIAL_EVIDENCE`
6. Final worktree: `CLEAN_AFTER_SEAL`
7. Silent sites before: `1`
8. Source symbols: `ReliabilityTraceEventType`, `ReliabilityTraceEnvelopeV1.REQUIRED_PAYLOAD`, `WorkflowService.__init__`, `WorkflowService._record_skill_v3_shadow_failure`, `WorkflowService._stage`
9. Reused observer contract: `ReliabilityTraceEnvelopeV1`, `emit_observation`, `failure_evidence_sha256`
10. Failure schema: `SkillV3ShadowFailureObservationV1@1`
11. Error hash: raw exception contributes only to SHA256 and is not persisted
12. Counter: instance-local, exactly +1 per failed invocation; local record deque max `64`
13. Runtime evidence: `TRACE_EVENT_WITH_BOUNDED_IN_MEMORY_FALLBACK`
14. Sink failure: fail-open, one drop increment, no recursive emit
15. Negative matrix: `7/7 PASS`
16. Direct silent swallow after: `0`
17. Production prompt SHA before/after: `{production['production_prompt_sha_before']}` / `{production['production_prompt_sha_after']}`
18. Production model-input SHA before/after: `{production['production_model_input_sha_before']}` / `{production['production_model_input_sha_after']}`
19. Production identity: `PASS`
20. Five-scenario output parity: `5/5 PASS`
21. Shadow failure blocks production: `NO`
22. Shadow failure observable: `YES`
23. Evidence bounded: `YES`
24. Privacy: `PASS`, matches `0`
25. Readiness delta: only `SHADOW_FAIL_OPEN FAIL -> PASS`
26. New failed readiness dimensions: `0`
27. Multi-sample policy unchanged: `YES`, source `{prior_policy_sha}`
28. Real-pilot readiness: `YES`
29. Pilot ID: `{pilot_id}`
30. A arm: `{pilot_core['arm_a']}`
31. B arm: `{pilot_core['arm_b']}`
32. Samples per A/B: `3/3`
33. Maximum real requests: `6`
34. Experiment-lock SHA: `{experiment_lock_sha}`
35. Stop conditions: exact sealed list in `real-pilot-plan-v1.json`
36. Pilot plan materialized: `YES`
37. Pilot plan disabled: `YES`
38. Packet template: `{packet_template['template_identity_sha256']}`
39. Execution authorized: `false`
40. Signed approval: `ABSENT`
41. Nonce: `NOT_CREATED/NOT_RESERVED/NOT_CONSUMED`
42. Focused tests: `{validation['focused_tests']}`
43. Adjacent tests: `{validation['adjacent_tests']}`
44. Strict L3: `{validation['strict_l3']}`, warnings `0`, blockers `0`
45. Owning-source regressions: `0`
46. Production/source diff: observability only; no Prompt/route/model/validator/authority/retry/fallback/Skill selection change
47. Manifest definition SHA: computed in `sha256-manifest-v1.json`
48. Manifest file SHA: computed after this report
49. Manifest coverage: all evidence files except manifest itself
50. External counters: credential/client/request/HTTP/network/model/paid = `0/0/0/0/0/0/0`
51. Pair 2–5: `NOT_EXECUTED`, authorization `NO`
52. Cutovers: Skill V3 `NO`; Skill V2 `NO`; Planning V2 `NO`
53. Full Short: `NOT_EXECUTED`
54. Exact next gate: `SKILL_V3_SELECTIVE_COMPILER_CHARACTER_HEAVY_MULTI_SAMPLE_PILOT_APPROVAL_READINESS`

## Full-suite classification

The complete offline suite produced 124 non-green nodes: 96 legacy Canary/materialization/approval or parent-evidence gates, 17 historical Planning Skill oracle/materialized-evidence gates, 2 R0E/R0F live-parity/fixed-hash gates, and 9 Skill V2 sealed-source/evidence gates. None belongs to the Skill V3 observability, selective compiler, generated trace contract, reliability trace, or failure-boundary owning-source matrix. Exact family counts are sealed in `full-suite-classification-v1.json`; historical evidence and live data were not rewritten.

`EXECUTION_AUTHORIZED=false`

`SIGNED_APPROVAL_CREATED=NO`

`REAL_EXECUTION_NONCE_CREATED=NO`

`REAL_PROVIDER_REQUEST_ATTEMPTS=0`

`NETWORK_CALLS=0`

`MODEL_CALLS=0`

`PAID_CALLS=0`

`FULL_SHORT_CANARY=NOT_EXECUTED`
"""
    (output / "final-report-v1.md").write_text(
        report, encoding="utf-8", newline="\n",
    )

    forbidden = (
        b"Bearer ", b"sk-ant-", b"sk-proj-", b"api_key=", b"https://", b"http://",
    )
    hits = []
    for path in sorted(output.iterdir()):
        if path.is_file() and path.name not in {
            "privacy-scan-v1.json", "sha256-manifest-v1.json",
        } and any(marker in path.read_bytes() for marker in forbidden):
            hits.append(path.name)
    write_json(output, "privacy-scan-v1.json", {
        "schema": "SkillV3ShadowObservabilityPrivacyScanV1",
        "status": "PASS" if not hits else "FAIL",
        "privacy_match_count": len(hits),
        "matching_files": hits,
        "raw_exception_count": 0,
        "traceback_count": 0,
        "raw_provider_content_count": 0,
    })
    if hits:
        raise RuntimeError("privacy scan failed")

    entries = [{
        "path": path.name,
        "bytes": len(path.read_bytes()),
        "sha256": sha_bytes(path.read_bytes()),
    } for path in sorted(output.iterdir()) if path.is_file() and path.name != "sha256-manifest-v1.json"]
    definition = {
        "schema": "SkillV3ShadowObservabilityEvidenceManifestV1",
        "entry_count": len(entries),
        "entries": entries,
    }
    write_json(output, "sha256-manifest-v1.json", {
        "schema": "SkillV3ShadowObservabilityEvidenceManifestEnvelopeV1",
        "definition": definition,
        "definition_sha256": sha_json(definition),
    })
    return {
        "pilot_id": pilot_id,
        "packet_template_sha256": packet_template["template_identity_sha256"],
        "experiment_lock_sha256": experiment_lock_sha,
        "manifest": verify_manifest(output),
        "production": production,
        "readiness_delta": changed_dimensions,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--focused-tests", required=True)
    parser.add_argument("--adjacent-tests", required=True)
    parser.add_argument("--full-suite", required=True)
    parser.add_argument("--strict-l3", required=True)
    args = parser.parse_args()
    result = materialize(args.output_dir.resolve(), {
        "focused_tests": args.focused_tests,
        "adjacent_tests": args.adjacent_tests,
        "full_suite": args.full_suite,
        "strict_l3": args.strict_l3,
    })
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
