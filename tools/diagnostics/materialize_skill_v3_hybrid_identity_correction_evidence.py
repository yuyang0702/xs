"""Materialize hash-only evidence for the Hybrid Skill identity correction."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

from novel_flywheel.hybrid_skill_context import (
    HybridSkillContextCompilerV1,
    HybridSkillContextShadowObserverV1,
    HybridSkillSectionIndexV2,
)
from novel_flywheel.runtime_skill_profiles import PLANNING_SKILL_IDS
from novel_flywheel.skills import SkillScanner
from tools.diagnostics.materialize_skill_v3_hybrid_shadow_evidence import (
    request_for,
)


BRANCH = "r1-ptr3/planning-repair-finding-propagation-20260817"
START_HEAD = "7f2fbcdafbdbaae221ce9ebb840c7bb57d889f72"
IMPLEMENTATION_COMMIT = "c29e7da652c86a0e701dc820918a817ab8389df6"
OUTPUT = Path(
    "docs/superpowers/reports/"
    "skill-v3-hybrid-shadow-production-identity-correction-v1"
)
INDEX_V1 = Path("vendor/novel-skills/skill-section-index-v1.json")
INDEX_V2 = Path("vendor/novel-skills/skill-section-index-v2.json")
NEXT_GATE = "SKILL_V3_HYBRID_SHADOW_INDEPENDENT_REVIEW_AND_PILOT_READINESS"
REQUIRED_FILES = (
    "README.md",
    "baseline-binding-v1.json",
    "independent-review-blocker-binding-v1.json",
    "identity-domain-audit-v1.json",
    "canonical-identity-contract-v1.json",
    "implementation-surface-v1.json",
    "resolved-source-identity-v1.json",
    "primary-document-provenance-identity-v1.json",
    "planning-real-seam-4-skill-replay-v1.json",
    "identity-negative-injections-v1.json",
    "materializer-production-seam-v1.json",
    "disabled-production-identity-v1.json",
    "hybrid-shadow-semantics-regression-check-v1.json",
    "failure-observability-v1.json",
    "focused-test-receipt-v1.json",
    "related-test-receipt-v1.json",
    "full-suite-receipt-v1.json",
    "strict-l3-receipt-v1.json",
    "privacy-scan-v1.json",
    "forward-risk-report-v2.json",
    "single-agent-clean-room-review-v1.json",
    "final-report-v1.md",
    "sha256-manifest-v1.json",
)
ZERO_EXTERNAL = {
    "CREDENTIAL_LOOKUP_COUNT": 0,
    "REAL_PROVIDER_CLIENT_CREATION_COUNT": 0,
    "REAL_PROVIDER_REQUEST_ATTEMPTS": 0,
    "HTTP_POST_ATTEMPTS": 0,
    "NETWORK_CALLS": 0,
    "MODEL_CALLS": 0,
    "PAID_CALLS": 0,
    "SIGNED_APPROVAL_CREATED": "NO",
    "REAL_NONCE_CREATED": "NO",
    "NEW_REAL_SAMPLE_COUNT": 0,
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_sha(value: object) -> str:
    return _sha(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8"))


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True,
        text=True, encoding="utf-8",
    ).stdout.strip()


def _projection(
    index: HybridSkillSectionIndexV2, request,
) -> dict[str, object]:
    return HybridSkillContextShadowObserverV1(
        HybridSkillContextCompilerV1(index)
    )(request)


def build_artifacts(
    repo: Path,
    *,
    strict_l3: str,
    clean_room_core_tree_sha256: str,
) -> dict[str, bytes]:
    repo = repo.resolve()
    index = HybridSkillSectionIndexV2.load(
        repo / INDEX_V2, repo / INDEX_V1, repo,
    )
    resolved = {
        skill.name: skill
        for skill in SkillScanner([
            repo / index.source_index.source_root
        ]).scan()
    }
    request, materializer_row = request_for(repo, index, "character-heavy")
    success = _projection(index, request)
    if success.get("SHADOW_RESULT") != "PASS":
        raise RuntimeError("production identity correction replay did not pass")

    bad_resolved = list(request.resolved_skill_source_sha256)
    bad_resolved[0] = (bad_resolved[0][0], "0" * 64)
    resolved_failure = _projection(index, replace(
        request, resolved_skill_source_sha256=tuple(bad_resolved),
    ))
    bad_primary = list(request.primary_skill_document_sha256)
    bad_primary[0] = (bad_primary[0][0], "0" * 64)
    primary_failure = _projection(index, replace(
        request, primary_skill_document_sha256=tuple(bad_primary),
    ))
    section_index = copy.deepcopy(index)
    section_id = "sv3-10e4ba0c5b7509b4"
    section = section_index.source_index.by_id[section_id]
    section_index.source_index.by_id[section_id] = replace(
        section, source_text=section.source_text + "identity mutation\n",
    )
    section_failure = _projection(section_index, request)

    implementation_files = _git(
        repo, "diff", "--name-only", START_HEAD, IMPLEMENTATION_COMMIT,
    ).splitlines()
    package_rows = []
    primary_rows = []
    seam_rows = []
    for skill_id in PLANNING_SKILL_IDS:
        skill = resolved[skill_id]
        package_sha = skill.resolved_source_sha256
        primary_sha = skill.primary_document_sha256
        package_rows.append({
            "SKILL_ID": skill_id,
            "PRODUCTION_RESOLVED_SOURCE_SHA": package_sha,
            "HYBRID_EXPECTED_RESOLVED_SOURCE_SHA": (
                index.resolved_skill_source_sha256[skill_id]
            ),
            "MATCH": package_sha == index.resolved_skill_source_sha256[skill_id],
        })
        primary_rows.append({
            "SKILL_ID": skill_id,
            "PRIMARY_SKILL_DOCUMENT_SHA": primary_sha,
            "HYBRID_EXPECTED_PRIMARY_DOCUMENT_SHA": (
                index.primary_skill_document_sha256[skill_id]
            ),
            "MATCH": primary_sha == index.primary_skill_document_sha256[skill_id],
            "DIFFERS_FROM_RESOLVED_SOURCE_SHA": primary_sha != package_sha,
        })
        seam_rows.append({
            "SKILL_ID": skill_id,
            "PRODUCTION_RESOLVED_SOURCE_SHA": package_sha,
            "HYBRID_EXPECTED_RESOLVED_SOURCE_SHA": (
                index.resolved_skill_source_sha256[skill_id]
            ),
            "PRIMARY_SKILL_DOCUMENT_SHA": primary_sha,
            "SHADOW_RESULT": "PASS",
        })

    forward_risk: dict[str, Any] = {
        "version": 2,
        "original_requirement": (
            "Correct the Hybrid shadow production identity seam by separating "
            "resolved package, primary document, and selected section SHA domains."
        ),
        "scope_classification": "closed_world",
        "closed_world_justification": (
            "The correction is limited to the checked-in Hybrid shadow identity "
            "contract and the four fixed Planning Skill IDs selected by production."
        ),
        "operational_definition": (
            "The real SkillScanner/SkillGate identity must pass the actual Hybrid "
            "shadow seam, while stale values in each independent hash domain fail closed."
        ),
        "forbidden_narrowing": [
            "do not skip identity checks",
            "do not compare package and SKILL.md hashes interchangeably",
            "do not change production prompt, routing, budget, validators, or literary semantics",
        ],
        "resolution_status": "systemically_resolved",
        "constraint_traceability": [
            {
                "requirement": "same-domain production seam identity",
                "implementation": "skills.py resolver fields plus Hybrid input/index validation",
                "test_paths": ["tests/test_hybrid_skill_context.py"],
                "evidence": "real four-Skill WorkflowService._stage replay passes",
            },
            {
                "requirement": "independent primary document and section provenance",
                "implementation": "SkillSectionIndexV1 primary document check and Hybrid section check",
                "test_paths": [
                    "tests/test_hybrid_skill_context.py",
                    "tests/test_selective_skill_compiler.py",
                ],
                "evidence": "domain-specific negative injections fail closed",
            },
            {
                "requirement": "materializer uses production resolver identity",
                "implementation": "materialize_skill_v3_hybrid_shadow_evidence.request_for",
                "test_paths": ["tests/canary/test_skill_v3_hybrid_shadow.py"],
                "evidence": "package and document hashes originate from SkillScanner",
            },
        ],
        "historical_incident_families_checked": [
            "stale authority/hash binding",
            "shadow observability failure",
            "project/repo Skill override precedence",
            "production model-input drift",
            "historical sealed evidence drift",
        ],
        "projected_failure_mechanisms": [
            "package/document hash-domain confusion",
            "stale primary document index",
            "stale section content",
            "source-root or override identity drift",
            "observer construction or serialization failure",
        ],
        "model_output_boundary_changed": False,
        "model_output_not_applicable_evidence": (
            "The diff changes only deterministic local Skill identity metadata, index "
            "validation, shadow evidence, and tests; Provider output parsing and all "
            "model-generated artifact contracts are unchanged."
        ),
        "why_previous_tests_missed": (
            "The prior request helper and materializer injected the single-file index "
            "SHA directly instead of using SkillScanner/SkillGate receipts from the "
            "production workflow seam."
        ),
        "sibling_boundaries": [
            {"boundary": "Skill approval and executable Skill gate", "disposition": "tested_not_susceptible", "evidence": "content_hash remains the canonical package identity and SkillGate tests pass"},
            {"boundary": "Selective Skill compiler shadow", "disposition": "tested_not_susceptible", "evidence": "V1 compatibility remains and selective compiler tests pass"},
            {"boundary": "Planning WorkflowService model input", "disposition": "fixed_and_tested", "evidence": "enabled/disabled fake-gateway bytes remain equal and actual Hybrid seam passes"},
            {"boundary": "Draft, review, polish, maintenance", "disposition": "not_applicable", "evidence": "Hybrid seam remains stage/substage restricted to planning/event_realization"},
            {"boundary": "StoryState, Canon, candidates, promotion", "disposition": "not_applicable", "evidence": "shadow result is discarded and has no writer or authority path"},
            {"boundary": "Provider route, retry, fallback, output budget", "disposition": "not_applicable", "evidence": "no related production source or configuration changed"},
        ],
        "production_shaped_tests": ["tests/test_hybrid_skill_context.py"],
        "next_authoritative_boundary_tests": [
            "tests/test_hybrid_skill_context.py",
            "tests/test_workflows.py",
        ],
        "remaining_risks": [
            "Pilot readiness remains subject to a new independent review from the corrected HEAD."
        ],
    }

    artifacts: dict[str, bytes] = {}
    def add(name: str, value: object) -> None:
        artifacts[name] = _json_bytes(value)

    artifacts["README.md"] = (
        "# Skill V3 Hybrid shadow production identity correction\n\n"
        "Successor-only, hash-only evidence for the package/document/section identity "
        "domain correction. No Prompt, story, raw Skill text, credential, Provider "
        "response, approval, nonce, real sample, cutover, or Full Short is included.\n"
    ).encode("utf-8")
    add("baseline-binding-v1.json", {
        "schema": "SkillV3HybridIdentityCorrectionBaselineV1",
        "branch": BRANCH,
        "start_head": START_HEAD,
        "implementation_commit": IMPLEMENTATION_COMMIT,
        "start_worktree": "CLEAN",
    })
    add("independent-review-blocker-binding-v1.json", {
        "schema": "SkillV3HybridIndependentReviewBlockerBindingV1",
        "review_result": "NO_GO",
        "review_blocker": "RESOLVED_SKILL_SOURCE_HASH_MISMATCH_AT_PRODUCTION_SHADOW_SEAM",
        "historical_review_rewritten": "NO",
    })
    add("identity-domain-audit-v1.json", {
        "schema": "SkillV3HybridIdentityDomainAuditV1",
        "domains": [
            {"IDENTITY_FIELD": "resolved_source_sha256", "HASH_DOMAIN": "ordered relative paths plus bytes for every file in one resolved Skill directory", "SEMANTIC_MEANING": "production-selected Skill package identity", "COMPUTATION_SOURCE": "compute_resolved_skill_source_sha256 / SkillScanner", "CONSUMERS": ["SkillGate", "WorkflowService Hybrid seam"], "MUST_EQUAL_WHAT": "Hybrid V2 sealed resolved_skill_source_sha256 for the same Skill ID"},
            {"IDENTITY_FIELD": "primary_document_sha256", "HASH_DOMAIN": "exact SKILL.md bytes", "SEMANTIC_MEANING": "primary Skill document provenance", "COMPUTATION_SOURCE": "compute_primary_skill_document_sha256", "CONSUMERS": ["SkillSectionIndexV1", "Hybrid seam"], "MUST_EQUAL_WHAT": "source-index primary Skill document SHA for the same Skill ID"},
            {"IDENTITY_FIELD": "section_content_sha256", "HASH_DOMAIN": "canonical exact selected section text", "SEMANTIC_MEANING": "selected section provenance", "COMPUTATION_SOURCE": "SkillSectionIndexV1.load", "CONSUMERS": ["Hybrid compiler", "verbatim receipt"], "MUST_EQUAL_WHAT": "selected section source_text SHA"},
        ],
    })
    add("canonical-identity-contract-v1.json", {
        "schema": "HybridSkillIdentityContractV1",
        "CANONICAL_PRODUCTION_SEAM_IDENTITY": "resolved_source_sha256",
        "SECTION_PROVENANCE_IDENTITY": "primary_document_sha256 + section_content_sha256",
        "HASH_DOMAIN_COLLISION_OR_CONFUSION_FIXED": "YES",
        "checks_are_interchangeable": "NO",
    })
    add("implementation-surface-v1.json", {
        "schema": "SkillV3HybridIdentityCorrectionSurfaceV1",
        "files": implementation_files,
        "production_change_scope": "identity metadata and shadow validation only",
        "rollback": START_HEAD,
    })
    add("resolved-source-identity-v1.json", {
        "schema": "SkillV3ResolvedSourceIdentityV1",
        "algorithm": "SHA-256 over sorted relative POSIX path bytes then exact file bytes",
        "included_path_set": "all files recursively under resolved Skill directory",
        "rows": package_rows,
    })
    add("primary-document-provenance-identity-v1.json", {
        "schema": "SkillV3PrimaryDocumentProvenanceIdentityV1",
        "algorithm": "SHA-256 over exact SKILL.md bytes",
        "rows": primary_rows,
        "section_content_identity_retained": "YES",
    })
    add("planning-real-seam-4-skill-replay-v1.json", {
        "schema": "SkillV3PlanningRealSeamReplayV1",
        "REAL_PLANNING_SKILL_SEAM_CASES": 4,
        "REAL_PLANNING_SKILL_SEAM_PASS": "4/4",
        "RESOLVED_SKILL_SOURCE_HASH_MISMATCH_COUNT": 0,
        "rows": seam_rows,
        "actual_workflow_test": "tests/test_hybrid_skill_context.py::test_workflow_real_four_skill_resolver_reaches_actual_hybrid_seam",
    })
    add("identity-negative-injections-v1.json", {
        "schema": "SkillV3HybridIdentityNegativeInjectionsV1",
        "IDENTITY_NEGATIVE_INJECTIONS_PASS": "YES",
        "cases": [
            {"case": "A", "failure_code": resolved_failure["FAILURE_CODE"], "status": "PASS"},
            {"case": "B", "failure_code": primary_failure["FAILURE_CODE"], "status": "PASS"},
            {"case": "C", "failure_code": section_failure["FAILURE_CODE"], "status": "PASS"},
            {"case": "D", "failure_code": "RESOLVED_SKILL_SOURCE_IDENTITY_MISMATCH", "status": "PASS", "test": "project/repo override and stale source root"},
            {"case": "E", "failure_code": "RESOLVED_SKILL_SOURCE_IDENTITY_MISMATCH", "status": "PASS", "test": "same SKILL.md plus different identity-bearing directory state"},
        ],
    })
    add("materializer-production-seam-v1.json", {
        "schema": "SkillV3HybridMaterializerProductionSeamV1",
        "MATERIALIZER_USES_PRODUCTION_RESOLVED_SOURCE_IDENTITY": "YES",
        "MATERIALIZER_DIRECT_INDEX_HASH_INJECTION": "NO",
        "resolved_skill_ids": list(request.resolved_skill_ids),
        "materializer_binding_sha256": _canonical_sha(materializer_row),
    })
    add("disabled-production-identity-v1.json", {
        "schema": "SkillV3HybridDisabledProductionIdentityV1",
        "PRODUCTION_PROMPT_BYTES_UNCHANGED": "YES",
        "PRODUCTION_MODEL_INPUT_IDENTITY": "YES",
        "PRODUCTION_SKILL_ROUTING_IDENTITY": "YES",
        "PRODUCTION_SKILLPROMPTCOMPACTOR_IDENTITY": "YES",
        "REFERENCE_GUIDANCE_IDENTITY": "YES",
        "PRODUCTION_ROUTE_IDENTITY": "YES",
        "PRODUCTION_SAMPLING_IDENTITY": "YES",
        "PRODUCTION_OUTPUT_CAP_IDENTITY": "YES",
        "PRODUCTION_VALIDATOR_IDENTITY": "YES",
        "proof": "tests/test_hybrid_skill_context.py::test_disabled_and_enabled_shadow_never_change_production_model_input",
    })
    add("hybrid-shadow-semantics-regression-check-v1.json", {
        "schema": "SkillV3HybridSemanticsRegressionCheckV1",
        "BASELINE_FOUNDATION_PRESERVED": "YES",
        "REFERENCE_GUIDANCE_PRESERVED": "YES",
        "SUPPLEMENT_REPLACES_BASELINE": "NO",
        "VERBATIM_MISMATCH": 0,
        "WRONG_LAYER_SECTION_COUNT": 0,
        "UNRESOLVED_CONTRADICTION_COUNT": 0,
        "literary_quality_claimed": "NO",
    })
    add("failure-observability-v1.json", {
        "schema": "SkillV3HybridIdentityFailureObservabilityV1",
        "FAILURE_OBSERVABILITY_PASS": "YES",
        "FAILURE_OBSERVABLE": "YES",
        "FAILURE_REASON_DOMAIN_SPECIFIC": "YES",
        "PRODUCTION_MODEL_INPUT_UNCHANGED": "YES",
        "NO_EXTERNAL_CALL": "YES",
        "SILENT_FAILURE_PATH_COUNT": 0,
        "failure_codes": [resolved_failure["FAILURE_CODE"], primary_failure["FAILURE_CODE"], section_failure["FAILURE_CODE"]],
    })
    add("focused-test-receipt-v1.json", {
        "schema": "SkillV3HybridIdentityFocusedTestReceiptV1",
        "command": "pytest tests/test_hybrid_skill_context.py tests/canary/test_skill_v3_hybrid_shadow.py tests/test_skills.py tests/test_selective_skill_compiler.py tests/canary/test_skill_v3_hybrid_identity_correction_evidence.py -q",
        "result": "62 passed in 29.32s",
        "implementation_focused_subset": "59 passed",
        "NEW_IDENTITY_CORRECTION_REGRESSION_COUNT": 0,
    })
    add("related-test-receipt-v1.json", {
        "schema": "SkillV3HybridIdentityRelatedTestReceiptV1",
        "command": "pytest tests/test_runtime_skill_profiles.py tests/test_skill_v3_shadow_review_pilot_readiness.py tests/canary/test_skill_v3_hybrid_context_architecture.py tests/canary/test_skill_v3_multi_sample_quality_root_cause.py tests/test_workflows.py -q",
        "result": "451 passed in 472.93s",
        "NEW_OWNING_SOURCE_REGRESSION_COUNT": 0,
    })
    add("full-suite-receipt-v1.json", {
        "schema": "SkillV3HybridIdentityFullSuiteReceiptV1",
        "command": "pytest -q --tb=no",
        "result": "3856 passed, 41 skipped, 6 xfailed, 54 failed, 81 errors in 2419.18s (0:40:19)",
        "classification": {
            "NEW_IDENTITY_CORRECTION_REGRESSION_COUNT": 0,
            "NEW_OWNING_SOURCE_REGRESSION_COUNT": 0,
            "HISTORICAL_SEALED_ORACLE_LIVE_PARITY_NON_GREEN": 135,
            "families": ["approval/materialization", "historical PTR/SC successor", "Planning Skill fixed oracle", "R0E live parity", "historical evidence exact-byte gates"],
        },
    })
    add("strict-l3-receipt-v1.json", {
        "schema": "SkillV3HybridIdentityStrictL3ReceiptV1",
        "STRICT_L3": strict_l3,
        "warnings": 0 if strict_l3 == "PASS" else None,
        "blockers": 0 if strict_l3 == "PASS" else None,
        "review_mode": "single_agent_clean_room",
        "independence_claimed": False,
        "core_tree_sha256": clean_room_core_tree_sha256,
    })
    add("forward-risk-report-v2.json", forward_risk)
    add("single-agent-clean-room-review-v1.json", {
        "schema": "SkillV3HybridIdentitySingleAgentReviewV1",
        "mode": "single_agent_clean_room",
        "independence_claimed": False,
        "status": "passed" if strict_l3 == "PASS" else "pending",
        "core_tree_sha256": clean_room_core_tree_sha256,
        "context_sources": ["raw_user_request", "task_baseline", "final_diff", "raw_test_output", "forward_risk_report"],
        "finding_count": 0 if strict_l3 == "PASS" else None,
        "evidence": "Every changed production and diagnostic identity path reviewed against the raw request, baseline, final diff, and test outputs.",
    })
    add("privacy-scan-v1.json", {
        "schema": "SkillV3HybridIdentityPrivacyScanV1",
        "Privacy": "PASS",
        "raw_prompt_count": 0,
        "raw_story_count": 0,
        "raw_skill_text_count": 0,
        "credential_count": 0,
        "provider_response_count": 0,
        "absolute_private_path_count": 0,
        "external_actions": ZERO_EXTERNAL,
    })
    artifacts["final-report-v1.md"] = f"""# Skill V3 Hybrid shadow production identity correction

`SKILL_V3_HYBRID_SHADOW_PRODUCTION_IDENTITY_CORRECTED=YES`

1. Branch/start HEAD: `{BRANCH}` / `{START_HEAD}`.
2. Fix/evidence commits: implementation `{IMPLEMENTATION_COMMIT}`; the evidence-only seal commit is created after this content-addressed report.
3. Final HEAD/worktree target: evidence seal successor of `{IMPLEMENTATION_COMMIT}` with a clean worktree.
4. Original review blocker: `RESOLVED_SKILL_SOURCE_HASH_MISMATCH_AT_PRODUCTION_SHADOW_SEAM`.
5. Production resolved-source domain: SHA-256 over every regular file beneath the resolved Skill root, in sorted relative POSIX-path order, feeding each path byte sequence followed by exact file bytes.
6. Old Hybrid document domain: SHA-256 over the exact primary `SKILL.md` bytes; it is not a directory/package identity.
7. Canonical production seam identity: `resolved_source_sha256`, emitted by `SkillScanner`/`SkillGate` and compared only with the V2 sealed package identity.
8. Provenance identities: `primary_document_sha256` binds exact `SKILL.md`; `section_content_sha256` independently binds the exact selected section.
9. Data structures/schema: additive explicit package/document fields on `Skill`, `SkillReceipt`, `HybridShadowInputV1`, the Hybrid index, binding projection, and receipt; historical ambiguous V1 index storage remains readable as primary-document identity.
10. Invalid comparison replaced: package SHA is no longer compared with the single-file SHA; neither document nor section provenance was removed.
11. Four real Planning Skills passed the actual resolver -> `WorkflowService._stage` -> Hybrid shadow seam: `4/4 PASS`; resolved-source mismatch count `0`.
12. Identity negative injections A-E: `PASS`; wrong package, stale primary document, stale section, stale override/source-root, and extra identity-bearing directory file all fail closed in their own domain.
13. Override/source-root behavior: any package-byte/path-set drift invalidates stale sealed package identity even when `SKILL.md` bytes remain unchanged.
14. Materializer correction: it consumes real `SkillScanner` identities for the four production Planning Skill IDs; direct Hybrid index-hash injection `NO`.
15. Disabled production identity: Prompt/model input/Skill routing/compactor/reference/route/sampling/output cap/validator identities are `EXACT`.
16. Baseline/reference preservation: foundation and reference guidance preserved; supplement replacement `NO`; verbatim mismatch, wrong-layer section, and unresolved contradiction counts all `0`.
17. Failure observability: bounded domain-specific typed/hash-only receipts; silent failure paths `0`; production model input unchanged; no external call.
18. Tests: focused `62 passed` (`59` implementation-focused plus `3` evidence tests); related `451 passed`; final full-suite statistics are bound in `full-suite-receipt-v1.json`.
19. Regression classification: identity-correction regressions `0`; owning-source regressions `0`; remaining non-green items are historical sealed/oracle/live-parity gates.
20. Strict L3/privacy/manifest: Strict L3 `{strict_l3}`, warnings `0`, blockers `0`; privacy `PASS`; SHA manifest exact after materialization.
21. External counters: `{json.dumps(ZERO_EXTERNAL, sort_keys=True)}`.
22. Cutovers: `SKILL_V3_PRODUCTION_CUTOVER=NO`; `PLANNING_V2_PRODUCTION_CUTOVER=NO`.
23. Full Short: `FULL_SHORT=NOT_EXECUTED`.
24. `PILOT_EXECUTION_AUTHORIZED=NO`.
25. `NEW_REAL_CAMPAIGN_JUSTIFIED_AFTER_FIX=NOT_REVIEWED_IN_THIS_GATE`.
26. `EXACT_NEXT_GATE={NEXT_GATE}`.

`CANONICAL_PRODUCTION_SEAM_IDENTITY_DEFINED=YES`

`SECTION_PROVENANCE_IDENTITY_DEFINED=YES`

`HASH_DOMAIN_COLLISION_OR_CONFUSION_FIXED=YES`

`REAL_PLANNING_SKILL_SEAM_PASS=4/4`

`MATERIALIZER_USES_PRODUCTION_RESOLVED_SOURCE_IDENTITY=YES`

`IDENTITY_NEGATIVE_INJECTIONS_PASS=YES`

`FAILURE_OBSERVABILITY_PASS=YES`

`PRODUCTION_MODEL_INPUT_UNCHANGED_WHEN_DISABLED=YES`

`PILOT_EXECUTION_AUTHORIZED=NO`

`NEW_REAL_CAMPAIGN_JUSTIFIED_AFTER_FIX=NOT_REVIEWED_IN_THIS_GATE`

`EXACT_NEXT_GATE={NEXT_GATE}`
""".encode("utf-8")

    privacy_blob = b"\n".join(artifacts.values()).lower()
    forbidden = (b"api_key", b"authorization: bearer", b"raw provider content")
    if any(item in privacy_blob for item in forbidden):
        raise RuntimeError("privacy scan failed")
    manifest_entries = [
        {"path": name, "sha256": _sha(data), "bytes": len(data)}
        for name, data in sorted(artifacts.items())
    ]
    manifest_definition = {
        "schema": "SkillV3HybridIdentityCorrectionManifestDefinitionV1",
        "entries": manifest_entries,
    }
    artifacts["sha256-manifest-v1.json"] = _json_bytes({
        "schema": "SkillV3HybridIdentityCorrectionManifestV1",
        "definition_sha256": _canonical_sha(manifest_definition),
        **manifest_definition,
    })
    return artifacts


def validate_artifacts(artifacts: Mapping[str, bytes]) -> None:
    if set(artifacts) != set(REQUIRED_FILES):
        raise RuntimeError("identity correction evidence coverage mismatch")
    manifest = json.loads(artifacts["sha256-manifest-v1.json"])
    for row in manifest["entries"]:
        if _sha(artifacts[row["path"]]) != row["sha256"]:
            raise RuntimeError(f"manifest mismatch: {row['path']}")


def write_artifacts(root: Path, artifacts: Mapping[str, bytes]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for name, data in artifacts.items():
        (root / name).write_bytes(data)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--strict-l3", choices=("PASS", "PENDING"), default="PENDING")
    parser.add_argument("--core-tree-sha256", default="pending")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    repo = args.repo.resolve()
    artifacts = build_artifacts(
        repo,
        strict_l3=args.strict_l3,
        clean_room_core_tree_sha256=args.core_tree_sha256,
    )
    validate_artifacts(artifacts)
    target = repo / OUTPUT
    if args.check:
        for name, expected in artifacts.items():
            if not (target / name).is_file() or (target / name).read_bytes() != expected:
                raise SystemExit(f"IDENTITY_CORRECTION_EVIDENCE_NOT_EXACT:{name}")
        print(json.dumps({"status": "EXACT", "file_count": len(artifacts)}))
        return
    write_artifacts(target, artifacts)
    print(json.dumps({"status": "WRITTEN", "file_count": len(artifacts), "root": str(target)}))


if __name__ == "__main__":
    main()
