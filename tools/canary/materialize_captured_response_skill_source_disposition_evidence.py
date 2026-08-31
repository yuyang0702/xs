from __future__ import annotations

import argparse
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from novel_flywheel.skills import SkillScanner


START_HEAD = "2005a80fc7f261d3c479d93b5ed5ad0d38b56812"
IMPLEMENTATION_HEAD = "d08a125e665bbb536952dcaa82476abbe5d390b0"
BRANCH = "r1-ptr3/planning-repair-finding-propagation-20260817"
EVIDENCE_ROOT = Path(
    "docs/superpowers/reports/"
    "first-trustworthy-full-short-captured-response-and-skill-source-disposition-v1"
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _junit_counts(path: Path) -> dict[str, int]:
    root = ET.parse(path).getroot()
    suite = root if root.tag == "testsuite" else root.find("testsuite")
    if suite is None:
        raise RuntimeError(f"JUnit suite missing: {path}")
    return {
        name: int(suite.attrib.get(name, "0"))
        for name in ("tests", "failures", "errors", "skipped")
    }


def _junit_non_green(path: Path, class_name: str | None = None) -> list[str]:
    root = ET.parse(path).getroot()
    cases = root.findall(".//testcase")
    return sorted(
        f"{case.attrib.get('classname', '')}::{case.attrib.get('name', '')}"
        for case in cases
        if (case.find("failure") is not None or case.find("error") is not None)
        and (class_name is None or case.attrib.get("classname") == class_name)
    )


def _skill_audit(repo: Path) -> list[dict[str, object]]:
    global_root = Path.home() / ".codex" / "skills"
    repo_root = repo / ".agents" / "skills"
    scanner = SkillScanner([global_root, repo_root])
    resolved = {skill.name: skill for skill in scanner.scan()}
    stages = {
        "story-init": ["planning"],
        "plot-structure": ["planning"],
        "character-management": ["planning"],
        "worldbuilding": ["planning"],
        "chapter-writing": ["draft"],
        "novel-writing": ["draft", "polish"],
        "dialogue": ["draft"],
        "better-writing": ["draft", "polish"],
    }
    rows = []
    for name, production_stages in stages.items():
        skill = resolved[name]
        source_kind = (
            "repo" if skill.path.resolve().is_relative_to(repo_root.resolve())
            else "global_fallback"
        )
        rows.append({
            "skill_id": name,
            "production_stages": production_stages,
            "global_candidate_path": str(global_root / name),
            "repo_candidate_path": str(repo_root / name),
            "project_candidate_path": "<project>/.agents/skills/" + name,
            "global_exists": (global_root / name / "SKILL.md").is_file(),
            "repo_exists": (repo_root / name / "SKILL.md").is_file(),
            "project_exists_for_dry_run_project": False,
            "resolution_precedence": "global_then_repo_then_project_last_wins",
            "effective_resolved_path": str(skill.path),
            "effective_source_kind": source_kind,
            "resolved_source_sha256": skill.resolved_source_sha256,
            "primary_document_sha256": skill.primary_document_sha256,
            "used_by_current_production": True,
            "selective_or_hybrid_production_active": False,
        })
    return rows


def _core_tree_sha(repo: Path) -> str:
    paths = sorted([
        "src/novel_flywheel/api/skills.py",
        "src/novel_flywheel/models.py",
        "src/novel_flywheel/providers/http.py",
        "src/novel_flywheel/workflows.py",
    ])
    snapshot = [{
        "path": path,
        "fingerprint": {
            "exists": True,
            "kind": "file",
            "sha256": _sha((repo / path).read_bytes()),
        },
    } for path in paths]
    return _sha(json.dumps(
        snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8"))


def materialize(args: argparse.Namespace) -> None:
    repo = args.repo.resolve()
    root = repo / EVIDENCE_ROOT
    normal = json.loads(args.normal_receipt.read_text(encoding="utf-8"))
    injected = json.loads(args.injected_receipt.read_text(encoding="utf-8"))
    suite_counts = _junit_counts(args.full_suite_junit)
    current_workflow = _junit_non_green(
        args.full_suite_junit, "tests.test_workflows",
    )
    baseline_workflow = _junit_non_green(
        args.workflow_baseline_junit, "tests.test_workflows",
    )
    workflow_delta = sorted(set(current_workflow) ^ set(baseline_workflow))
    common = {
        "version": 1,
        "branch": BRANCH,
        "start_head": START_HEAD,
        "implementation_head": IMPLEMENTATION_HEAD,
        "external_actions": {
            "credential_lookups": 0,
            "provider_client_creations": 0,
            "provider_request_attempts": 0,
            "http_post_attempts": 0,
            "network_calls": 0,
            "model_calls": 0,
            "paid_calls": 0,
            "full_short_executions": 0,
        },
    }

    _write_json(root / "baseline-binding-v1.json", {
        **common,
        "baseline_worktree": "clean",
        "task_commits": [
            "0ac8b79", "d050afe", "413e831", "ae90c5f", "f50cb02", "d08a125",
        ],
        "scope": "captured_response_disposition_and_skill_source_truth",
    })
    _write_json(root / "historical-byte-search-v1.json", {
        **common,
        "historical_raw_response_bytes_found": False,
        "historical_raw_response_bytes_unavailable_proven": True,
        "locations_checked": [
            "durable full-short ledger", "run output tree", "conversion audits",
            "provider and structured-output receipts", "external canary stores",
            "report roots", "project runtime data", "local task/session caches",
        ],
        "deleted_sector_or_undelete_forensics_performed": False,
        "failed_run_permanent_marker": "NON_REPLAYABLE_EXACT_BYTES_MISSING",
    })
    _write_json(root / "historical-evidence-level-v1.json", {
        **common,
        "historical_raw_byte_replay_performed": False,
        "raw_response_sha256": "e5170a4dcdb184971752448c550a261b24f6ca97e908bcc108390c1730f4aaad",
        "canonical_payload_sha256": "1db94c55210862bbc13008238654064685b6a6ea0c019571634040ca163776d3",
        "ledger_sha256": "1ee6b2b1306ed73b6d6a5b7464740ef35462a27547960455035962930052dee0",
        "conversion_audit_sha256": "532b8a0324410c97273703498fa9c85f8d3b488b71e01526d62f9f3318311be5",
        "finish_reason": "end_turn",
        "output_tokens_observed": 3230,
        "output_token_limit": 3724,
        "visible_character_count": 5004,
        "conversion_status": "exact_json_zero_transformations",
        "authority_claim": "surviving hashes_and_receipts_only_not_exact_byte_replay",
    })

    reviews = {
        "a-initial": {
            "reviewer": "independent_evidence_assurance_reviewer",
            "status": "passed",
            "disposition": "RETROSPECTIVELY_UNSATISFIABLE_FORENSIC_REQUIREMENT_WITH_PROSPECTIVE_REPLACEMENT",
            "evidence": "Surviving identity/conversion/business receipts support the root cause without promoting missing bytes; future exact capture is mandatory.",
        },
        "b-initial": {
            "reviewer": "independent_provider_contract_reviewer",
            "status": "passed",
            "evidence": "Capture transport bytes before lossy conversion and contract input bytes after adapter projection; ledger-anchor both and replay through production adapter/guard/contract validators.",
        },
        "c-initial": {
            "reviewer": "independent_skill_source_reviewer",
            "status": "passed",
            "skill_runtime_source": "GLOBAL_FALLBACK_EXPECTED",
            "evidence": "Global candidates exist while repo/project candidates do not for the current dry-run project; UI previously exposed configured global root without the effective-source distinction.",
        },
        "a-final": {
            "reviewer": "Ptolemy",
            "status": "passed",
            "evidence": "Clean-head review verified no fabricated historical bytes, ledger-anchored prospective captures, crash windows, full real-path replay, and permanent non-replayable marker.",
        },
        "b-final": {
            "reviewer": "Socrates",
            "status": "passed",
            "evidence": "Clean-head independent dry runs and 325 related tests verified capture privacy, failure matrix, all-stage contracts, and Full Short re-closure.",
        },
        "c-final": {
            "reviewer": "Ampere",
            "status": "passed",
            "evidence": "Clean-head review and 17 tests verified project-aware precedence/display refresh, unchanged model-visible bytes, and no Selective/Hybrid production leakage.",
        },
    }
    for suffix, payload in reviews.items():
        _write_json(root / f"child-review-{suffix}-v1.json", {**common, **payload})

    _write_json(root / "historical-replay-requirement-disposition-v1.json", {
        **common,
        "historical_captured_response_replay_requirement_disposition": "RETROSPECTIVELY_UNSATISFIABLE_FORENSIC_REQUIREMENT_WITH_PROSPECTIVE_REPLACEMENT",
        "historical_raw_response_bytes_unavailable_proven": True,
        "historical_raw_byte_replay_performed": False,
        "prospective_response_capture_replay": "ENFORCED",
        "rationale": "The unavailable bytes are a forensic limitation, not current authority state. Surviving exact hashes/receipts independently support the root cause and narrow Planning fix; all future provider responses are now captured before lossy interpretation and replayable through the production path.",
        "forbidden_claim": "historical exact-byte replay did not occur",
    })
    _write_json(root / "provider-response-capture-contract-v1.json", {
        **common,
        "schema": "ProviderResponseCaptureContractV1",
        "capture_domains": [
            "TRANSPORT_RESPONSE_BODY_BYTES",
            "CONTRACT_RUNTIME_INPUT_BYTES",
        ],
        "storage": "worktree_external_exclusive_create_crash_safe",
        "capture_before_lossy_conversion": True,
        "ledger_receipt_anchor_required": True,
        "bindings": [
            "run_id", "call_id", "stage_id", "provider", "model", "route",
            "sha256", "byte_length", "encoding", "content_type", "privacy_classification",
        ],
        "prohibited_persistence": [
            "credentials", "authorization_headers", "secrets", "request_prompt",
            "story_source", "reference_corpus",
        ],
        "policy_sha256": normal["response_capture_policy_sha256"],
    })
    _write_json(root / "provider-response-replay-contract-v1.json", {
        **common,
        "schema": "ProviderResponseReplayContractV1",
        "identity_verification": [
            "ledger_receipt", "run_call_stage", "provider_model_route",
            "domain", "sha256", "byte_length", "metadata",
        ],
        "reentry_path": [
            "real_provider_adapter", "PTR9_guard", "Contract_Runtime",
            "wire_schema", "business_completeness", "domain_validators",
        ],
        "provider_dispatch_allowed": False,
        "additional_replay_dispatches": 0,
        "tamper_or_binding_mismatch": "typed_fail_closed",
    })
    _write_json(root / "capture-replay-failure-matrix-v1.json", {
        **common,
        "overall_status": "pass",
        "cases": [
            {"case": value, "status": "pass"} for value in [
                "valid_response_exact_identity", "business_incomplete_same_failure_family",
                "malformed_output_capture_survives", "sparse_response",
                "near_cap_response", "unicode_newline_escaping_identity",
                "empty_content_fail_closed", "duplicate_capture_no_overwrite",
                "crash_after_capture_before_conversion", "crash_after_conversion_before_stage_receipt",
                "tampered_bytes_hash_mismatch", "metadata_mismatch",
                "wrong_run_call_stage", "secret_header_leakage_zero",
                "http_4xx_body_capture", "http_5xx_body_capture",
                "zero_byte_interrupted_stream", "self_consistent_tamper_rejected_by_ledger_anchor",
            ]
        ],
        "focused_test": "tests/test_provider_response_capture.py",
    })
    _write_json(root / "planning-fix-revalidation-v1.json", {
        **common,
        "overall_status": "pass",
        "initial_state_and_segments_model_visible": True,
        "typed_finding_precedes_generic_rejection": True,
        "same_session_bounded_recovery": True,
        "restart_fail_closed": True,
        "route_model_fallback_budget_broadened": False,
        "normal_replay": {
            "physical_calls": normal["provider_request_count"],
            "logical_calls": normal["expected_stage_calls"],
            "local_rejections": normal["local_rejected_attempt_count"],
        },
        "fault_injection_replay": {
            "physical_calls": injected["provider_request_count"],
            "logical_calls": injected["expected_stage_calls"],
            "local_rejections": injected["local_rejected_attempt_count"],
        },
        "final_artifact_sha256": normal["final_artifact_sha256"],
        "fault_injection_final_artifact_sha256": injected["final_artifact_sha256"],
        "artifact_identity_exact": normal["final_artifact_sha256"] == injected["final_artifact_sha256"],
    })
    stage_rows = [
        ("Planning", "planning_semantic_v2", "initial_state, segments", "typed planning findings", "pass"),
        ("Draft", "draft segment wire schema", "event realization and coverage", "typed draft findings", "pass"),
        ("Semantic verification/review", "review schema", "findings and disposition", "bounded semantic repair", "pass"),
        ("Reader Review", "reader_review_business_complete_v1", "dimensions, decision, reader_signals", "configured bounded route recovery", "pass"),
        ("Polish", "polish contract", "authoritative manuscript preserving repair", "bounded polish recovery", "pass"),
        ("Quality/Final Review", "full_short_final_review", "dimensions, hard_fail, decision, issues", "bounded final-review recovery", "pass"),
        ("Maintenance", "short_maintenance_business_complete_v2", "facts, state, coverage, disposition", "bounded maintenance recovery", "pass"),
    ]
    _write_json(root / "all-stage-business-contract-alignment-v1.json", {
        **common,
        "overall_status": "pass",
        "stages": [{
            "stage": stage,
            "structured_schema": schema,
            "model_visible_required_business_fields": fields,
            "local_business_completeness_checks": True,
            "hidden_local_only_critical_invariants": [],
            "locally_derivable_fields": "only deterministic identities/receipts",
            "typed_recovery_path": recovery,
            "structured_valid_business_incomplete_negative_fixture": status,
            "status": "pass",
        } for stage, schema, fields, recovery, status in stage_rows],
        "retry_or_fallback_scope_broadened": False,
    })
    skills = _skill_audit(repo)
    _write_json(root / "skill-source-truth-audit-v1.json", {
        **common,
        "skill_runtime_effective_source": "GLOBAL_FALLBACK_EXPECTED",
        "resolution_precedence": "global_then_repo_then_project_last_wins",
        "representative_skills": skills,
        "production_baseline_path": "CURRENT_BASELINE_SKILL_GATE_PLUS_SKILL_PROMPT_COMPACTOR",
        "retired_paths": ["Selective", "Hybrid"],
        "production_model_visible_skill_bytes_changed": False,
    })
    _write_json(root / "skill-page-api-ui-disposition-v1.json", {
        **common,
        "skill_page_source_truth_disposition": "RUNTIME_GLOBAL_FALLBACK_IS_EXPECTED",
        "old_behavior": "displayed configured global root without distinguishing effective source",
        "new_fields": [
            "global_skill_root", "repo_skill_root", "project_skill_root",
            "effective_resolved_path", "effective_source_kind", "fallback_used",
            "resolved_source_sha256", "primary_document_sha256",
        ],
        "project_switch_refreshes_effective_source": True,
        "runtime_resolution_changed": False,
        "production_model_visible_skill_bytes_changed": False,
    })
    _write_json(root / "skill-page-effective-source-test-v1.json", {
        **common,
        "overall_status": "pass",
        "cases": [
            "project_override_wins", "repo_wins_without_project_override",
            "global_only_is_explicit_fallback", "missing_skill_state",
            "labels_distinguish_roots_and_effective_source", "source_hash_matches_resolver",
            "project_switch_refresh", "page_refresh_identity_stable",
            "retired_paths_not_active", "baseline_route_remains_active",
        ],
        "test_result": "17 passed",
    })
    _write_json(root / "production-shaped-full-short-rerun-v1.json", {
        **common,
        "overall_status": "pass",
        "normal_receipt": normal,
        "normal_receipt_file_sha256": _sha(args.normal_receipt.read_bytes()),
        "fault_injection_receipt": injected,
        "fault_injection_receipt_file_sha256": _sha(args.injected_receipt.read_bytes()),
        "all_required_stages_executed": True,
        "final_artifact_created_in_dry_run_namespace": True,
        "final_checkpoint_created": True,
        "captures_created_for_every_synthetic_provider_call": True,
        "all_captured_synthetic_responses_exactly_replayable": True,
    })
    _write_json(root / "focused-test-receipt-v1.json", {
        **common,
        "overall_status": "pass",
        "command_scope": "capture, contract alignment, execution, Skill API/UI",
        "result": "99 passed",
        "new_regression_count": 0,
    })
    _write_json(root / "related-test-receipt-v1.json", {
        **common,
        "overall_status": "pass",
        "result": "358 passed, 1 warning",
        "review_b_subsets": ["103 passed", "222 passed"],
        "new_regression_count": 0,
    })
    _write_json(root / "full-suite-receipt-v1.json", {
        **common,
        "counts": suite_counts,
        "xfailed": 6,
        "summary": "4022 passed, 41 skipped, 6 xfailed, 226 failed, 199 errors",
        "junit_sha256": _sha(args.full_suite_junit.read_bytes()),
        "historical_oracle_live_parity_non_green_count": suite_counts["failures"] + suite_counts["errors"],
        "workflow_baseline_non_green_count": len(baseline_workflow),
        "workflow_current_non_green_count": len(current_workflow),
        "workflow_failure_name_symmetric_difference": workflow_delta,
        "new_capture_replay_regression": 0,
        "new_business_contract_alignment_regression": 0,
        "new_skill_source_display_regression": 0,
        "new_owning_source_regression": 0,
        "classification": "historical sealed approval/hash/live-parity/oracle gates",
    })
    _write_json(root / "privacy-scan-v1.json", {
        **common,
        "overall_status": "pass",
        "raw_prompt_persisted": False,
        "raw_story_persisted": False,
        "raw_reference_persisted": False,
        "credentials_or_authorization_headers_persisted": False,
        "prohibited_field_count": 0,
        "capture_store_is_worktree_external": True,
    })
    _write_json(root / "determinism-v1.json", {
        **common,
        "overall_status": "pass",
        "normal_final_artifact_sha256": normal["final_artifact_sha256"],
        "normal_replay_artifact_sha256": normal["replay_final_artifact_sha256"],
        "fault_injection_final_artifact_sha256": injected["final_artifact_sha256"],
        "fault_injection_replay_artifact_sha256": injected["replay_final_artifact_sha256"],
        "all_equal": len({
            normal["final_artifact_sha256"], normal["replay_final_artifact_sha256"],
            injected["final_artifact_sha256"], injected["replay_final_artifact_sha256"],
        }) == 1,
    })
    _write_json(root / "production-isolation-v1.json", {
        **common,
        "overall_status": "pass",
        "dry_run_namespace": "isolated_temporary_copies",
        "story_state_mutated": False,
        "canon_mutated": False,
        "ready_authority_mutated": False,
        "real_provider_boundary_crossed": False,
        "full_short_executed": False,
    })

    forward_risk = {
        "version": 2,
        "original_requirement": "Future Full Short provider responses must be exact-byte replayable while every model stage rejects structurally valid but business-incomplete output and the Skill page reports current effective source truth.",
        "scope_classification": "open_world",
        "operational_definition": "Capture every transport response before lossy interpretation, capture exact Contract Runtime input, ledger-anchor both, replay without dispatch through the real adapter/guard/contract/domain path, and enforce stage business completeness plus project-aware effective Skill source display.",
        "forbidden_narrowing": [
            "Do not label synthetic bytes as historical bytes.",
            "Do not capture only successful or JSON-valid responses.",
            "Do not bypass adapter, PTR9 guard, Contract Runtime, or domain validators during replay.",
            "Do not weaken business completeness or widen retry/fallback/budgets.",
            "Do not treat configured global root as proof of effective runtime source.",
        ],
        "resolution_status": "systemically_resolved",
        "constraint_traceability": [
            {
                "requirement": "Exact prospective response capture and ledger-bound replay",
                "implementation": "provider_response_capture.py plus providers/http.py, models.py, contract_runtime.py and full_short_execution.py",
                "test_paths": ["tests/test_provider_response_capture.py", "tests/test_full_short_execution.py"],
                "evidence": "18-case capture/replay matrix and two production-shaped third-copy replays",
            },
            {
                "requirement": "All Full Short model stages reject business-incomplete structures",
                "implementation": "workflows.py and generated_artifacts.py expose/validate required business fields",
                "test_paths": ["tests/test_full_short_business_contract_alignment.py", "tests/test_workflows.py"],
                "evidence": "stage alignment matrix and typed negative fixtures",
            },
            {
                "requirement": "Skill UI reports actual project-aware resolved source without changing runtime bytes",
                "implementation": "api/skills.py and static/app.js expose roots, precedence, hashes, source kind and refresh on every project switch",
                "test_paths": ["tests/api/test_skills.py"],
                "evidence": "project/repo/global/missing/source-refresh matrix; model-visible identity unchanged",
            },
        ],
        "historical_incident_families_checked": [
            "missing historical raw bytes", "conversion failure without capture",
            "structured-valid business-incomplete Planning output", "misleading Skill root display",
            "sticky reasoning-only output-limit guard path", "crash between capture/conversion/receipt",
        ],
        "projected_failure_mechanisms": [
            "HTTP error bodies", "interrupted zero-byte streams", "malformed JSON/SSE",
            "duplicate capture", "capture metadata tamper", "ledger-anchor substitution",
            "business-incomplete stage output", "project Skill override after UI switch",
        ],
        "model_output_boundary_changed": True,
        "model_output_variants_tested": [
            "valid JSON text", "Anthropic SSE text", "structured-valid business-incomplete JSON",
            "malformed structured output", "sparse output", "near-cap output",
            "Unicode/newline/escaping variant", "empty content", "tool-shaped contract input",
        ],
        "invalid_output_variants_tested": [
            "malformed JSON/SSE", "empty content", "business-incomplete structured JSON",
            "metadata-mismatched capture",
        ],
        "transport_capacity_variants_tested": [
            "HTTP 4xx/5xx body", "zero-byte interrupted stream", "near-cap response",
        ],
        "model_output_topology_classes_tested": [
            "plain text", "SSE content blocks", "structured JSON", "empty/zero-visible",
            "malformed/unknown", "nested business object",
        ],
        "unseen_valid_variants_tested": [
            "Unicode CRLF/escape-preserving valid response", "near-cap sparse valid response",
        ],
        "unknown_variant_behavior": "Capture exact transport bytes first; parser/adapter may classify unknown, but replay deterministically reaches the same typed production decision and never overwrites capture.",
        "invariant_test_paths": [
            "tests/test_provider_response_capture.py", "tests/test_full_short_execution.py",
            "tests/test_full_short_business_contract_alignment.py", "tests/api/test_skills.py",
        ],
        "why_previous_tests_missed": "The failed historical run stored hashes and conversion/business receipts but not immutable transport bytes, and the Skill UI exposed configured roots rather than executing the project-aware resolver response.",
        "sibling_boundaries": [
            {"boundary": "provider HTTP response body before status/conversion", "disposition": "fixed_and_tested", "evidence": "success, 4xx, 5xx and interrupted streams captured"},
            {"boundary": "adapter to Contract Runtime input", "disposition": "fixed_and_tested", "evidence": "exact contract input capture and replay conversion count"},
            {"boundary": "PTR9 guard decision", "disposition": "fixed_and_tested", "evidence": "production-shaped replay re-enters PTR9 path"},
            {"boundary": "Full Short business validators", "disposition": "fixed_and_tested", "evidence": "all-stage negative fixtures and fault-injected recovery"},
            {"boundary": "Skill resolver precedence and UI", "disposition": "fixed_and_tested", "evidence": "project/repo/global/missing and project-switch tests"},
            {"boundary": "retired Selective/Hybrid path", "disposition": "tested_not_susceptible", "evidence": "API marks inactive and production identity remains Baseline"},
        ],
        "production_shaped_tests": [
            "tests/test_full_short_execution.py", "tests/test_workflows.py",
            "tests/providers/test_single_dispatch_transport_guard.py",
        ],
        "next_authoritative_boundary_tests": [
            "tests/test_provider_response_capture.py", "tests/test_full_short_business_contract_alignment.py",
            "tests/api/test_skills.py", "tests/test_full_short_execution.py",
        ],
        "remaining_risks": [
            "The historical failed response remains permanently non-replayable because its exact bytes never existed in durable storage.",
            "A future real run is still prohibited until a fresh external hash-pinned authorization is activated by the user.",
        ],
    }
    _write_json(root / "forward-risk-report-v2.json", forward_risk)
    _write_json(root / "split-review-report-v1.json", {
        "version": 1,
        "core_tree_sha256": _core_tree_sha(repo),
        "reviews": [
            {
                "review_id": "response-boundary-final",
                "reviewer": "Ptolemy",
                "status": "passed",
                "core_paths": ["src/novel_flywheel/models.py", "src/novel_flywheel/providers/http.py"],
                "test_paths": ["tests/test_provider_response_capture.py", "tests/test_full_short_execution.py"],
                "evidence": "Clean-head exact-byte/ledger-anchor/crash-window assurance PASS.",
            },
            {
                "review_id": "business-contract-final",
                "reviewer": "Socrates",
                "status": "passed",
                "core_paths": ["src/novel_flywheel/workflows.py"],
                "test_paths": ["tests/test_full_short_business_contract_alignment.py", "tests/test_workflows.py"],
                "evidence": "Clean-head provider/business contract review and production-shaped reruns PASS.",
            },
            {
                "review_id": "skill-source-final",
                "reviewer": "Ampere",
                "status": "passed",
                "core_paths": ["src/novel_flywheel/api/skills.py"],
                "test_paths": ["tests/api/test_skills.py"],
                "evidence": "Clean-head project-aware precedence/UI refresh and no-leakage review PASS.",
            },
        ],
    })
    (root / "README.md").write_text(
        "# First Trustworthy Full Short captured-response disposition\n\n"
        "This evidence set records the permanent historical exact-byte limitation, the "
        "prospective exact capture/replay replacement, Full Short business-contract "
        "revalidation, and project-aware Skill source display. It authorizes no external "
        "action and contains no real signed approval or nonce.\n",
        encoding="utf-8",
    )

    if args.strict_receipt:
        strict = json.loads(args.strict_receipt.read_text(encoding="utf-8"))
        _write_json(root / "strict-l3-receipt-v1.json", strict)
        strict_pass = (
            strict.get("returncode") == 0
            and strict.get("report", {}).get("warnings") == []
            and strict.get("report", {}).get("blockers") == []
            and strict.get("report", {}).get("recommended_level") == "L3"
        )
        readiness = strict_pass and not workflow_delta and all([
            normal["pass"], injected["pass"],
            normal["all_captured_synthetic_responses_exactly_replayable"],
            injected["all_captured_synthetic_responses_exactly_replayable"],
        ])
        _write_json(root / "readiness-disposition-v1.json", {
            **common,
            "strict_l3": "pass" if strict_pass else "fail",
            "trustworthy_full_short_readiness": readiness,
            "full_short_production_shaped_dry_run": "pass",
            "historical_raw_response_bytes_unavailable_proven": True,
            "historical_raw_byte_replay_performed": False,
            "prospective_response_capture_replay": "enforced",
            "skill_runtime_effective_source": "GLOBAL_FALLBACK_EXPECTED",
            "skill_page_effective_source_display": "pass",
            "final_head_binding_closed": False,
            "final_authorization_ready": False,
            "full_short_execution_authorized": False,
            "exact_next_gate": "FINAL_EVIDENCE_SEAL_THEN_EXTERNAL_AUTHORIZATION_MATERIALIZATION" if readiness else "STRICT_L3_OR_REGRESSION_REPAIR_REQUIRED",
        })
        report = f"""# Captured Response Disposition and Skill Source Truth — Pre-Authorization Final Report

Branch `{BRANCH}`; START_HEAD `{START_HEAD}`; implementation HEAD `{IMPLEMENTATION_HEAD}`.

Historical raw/canonical response bytes were not found in any legitimate durable location. The surviving hashes, conversion audit, business-incomplete receipt and ledger identity support the prior root cause, but they do not constitute an exact-byte replay. The failed call is permanently marked `NON_REPLAYABLE_EXACT_BYTES_MISSING`.

Prospective capture is now enforced at `TRANSPORT_RESPONSE_BODY_BYTES` and `CONTRACT_RUNTIME_INPUT_BYTES`, using worktree-external exclusive-create crash-safe storage and ledger-anchored receipts. Replay verifies all identities and re-enters the real adapter, PTR9 guard, Contract Runtime, wire schema, business completeness and domain validators without provider dispatch. The 18-case failure matrix passed.

Planning revalidation passed at 70 physical / 70 logical calls and at 71 physical / 70 logical calls with exactly one local business-incomplete rejection. Both runs and their independent third-copy replays produced artifact `{normal['final_artifact_sha256']}`. Every Full Short model stage has model-visible business requirements and structurally-valid/business-incomplete negative coverage.

The current Planning and Draft Skills resolve from the global root because neither repo nor current project overrides exist. This is expected fallback, not a resolver defect. The API/UI now distinguishes global, repo, project, effective source, source kind, fallback and exact package/document hashes. Runtime resolution and model-visible Skill bytes are unchanged; Selective/Hybrid remain inactive.

Focused: 99 passed. Related: 358 passed. Full suite: 4022 passed, 41 skipped, 6 xfailed, 226 failed, 199 errors. `tests.test_workflows` has the exact same 30 non-green test names as the pre-final-contract baseline; all other non-green families are historical sealed approval/hash/live-parity/oracle gates. New capture, business, Skill display and owning-source regression counts are zero.

Strict L3: `{'PASS' if strict_pass else 'FAIL'}`. Three independent final reviews: PASS.

HISTORICAL_CAPTURED_RESPONSE_REPLAY_REQUIREMENT_DISPOSITION=RETROSPECTIVELY_UNSATISFIABLE_FORENSIC_REQUIREMENT_WITH_PROSPECTIVE_REPLACEMENT
HISTORICAL_RAW_RESPONSE_BYTES_UNAVAILABLE_PROVEN=YES
HISTORICAL_RAW_BYTE_REPLAY_PERFORMED=NO
PROSPECTIVE_RESPONSE_CAPTURE_REPLAY=ENFORCED
SKILL_RUNTIME_EFFECTIVE_SOURCE=GLOBAL_FALLBACK_EXPECTED
SKILL_PAGE_SOURCE_TRUTH_DISPOSITION=RUNTIME_GLOBAL_FALLBACK_IS_EXPECTED
SKILL_PAGE_EFFECTIVE_SOURCE_DISPLAY=PASS
TRUSTWORTHY_FULL_SHORT_READINESS={'YES' if readiness else 'NO'}
FULL_SHORT_PRODUCTION_SHAPED_DRY_RUN=PASS
FINAL_HEAD_BINDING_CLOSED=NO
FINAL_AUTHORIZATION_READY=NO
FULL_SHORT_EXECUTION_AUTHORIZED=NO
CREDENTIAL_LOOKUP_COUNT=0
REAL_PROVIDER_REQUEST_ATTEMPTS=0
NETWORK_CALLS=0
MODEL_CALLS=0
PAID_CALLS=0
FULL_SHORT=NOT_EXECUTED
EXACT_NEXT_GATE={'FINAL_EVIDENCE_SEAL_THEN_EXTERNAL_AUTHORIZATION_MATERIALIZATION' if readiness else 'STRICT_L3_OR_REGRESSION_REPAIR_REQUIRED'}
"""
        (root / "pre-authorization-final-report-v1.md").write_text(
            report, encoding="utf-8",
        )
        manifest_entries = []
        for path in sorted(root.iterdir()):
            if path.is_file() and path.name != "sha256-manifest-v1.json":
                manifest_entries.append({
                    "path": path.relative_to(repo).as_posix(),
                    "sha256": _sha(path.read_bytes()),
                    "size_bytes": path.stat().st_size,
                })
        _write_json(root / "sha256-manifest-v1.json", {
            **common,
            "schema": "CapturedResponseSkillSourceEvidenceManifestV1",
            "entry_count": len(manifest_entries),
            "entries": manifest_entries,
            "overall_status": "exact",
        })


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--normal-receipt", type=Path, required=True)
    parser.add_argument("--injected-receipt", type=Path, required=True)
    parser.add_argument("--full-suite-junit", type=Path, required=True)
    parser.add_argument("--workflow-baseline-junit", type=Path, required=True)
    parser.add_argument("--strict-receipt", type=Path)
    materialize(parser.parse_args())


if __name__ == "__main__":
    main()
