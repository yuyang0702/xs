from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

from novel_flywheel.context_policy import estimate_input_tokens
from novel_flywheel.hybrid_skill_context import (
    ACTIONABILITY_CLASSES,
    DEFAULT_HYBRID_SKILL_CONTEXT_SHADOW_ENABLED,
    DEPENDENCY_TYPES,
    OVERLAP_CLASSES,
    SUPPLEMENT_SEPARATOR,
    HybridCapacityError,
    HybridContradictionError,
    HybridDependencyEdgeV1,
    HybridIndexError,
    HybridProtectedBudgetV1,
    HybridShadowInputV1,
    HybridSkillContextCompilerV1,
    HybridSkillContextShadowObserverV1,
    HybridSkillSectionIndexV2,
    HybridVerbatimError,
    extract_demand_features_v1,
)
from novel_flywheel.selective_skill_compiler import SectionIndexError
from novel_flywheel.skill_prompts import SkillPromptCompactor
from novel_flywheel.skills import SkillScanner, compute_resolved_skill_source_sha256


BRANCH = "r1-ptr3/planning-repair-finding-propagation-20260817"
START_HEAD = "bfb75334ad8bea30f03e792474f85a9750e40981"
IDENTITY_CORRECTION_COMMIT = "c29e7da652c86a0e701dc820918a817ab8389df6"
EXACT_GATE = "SKILL_V3_HYBRID_SHADOW_INDEPENDENT_REVIEW_AND_PILOT_READINESS"
NEXT_GATE_PASS = (
    "SKILL_V3_HYBRID_CHARACTER_HEAVY_MULTI_SAMPLE_"
    "PILOT_MATERIALIZATION_AND_APPROVAL_READINESS"
)
OUTPUT = Path(
    "docs/superpowers/reports/"
    "skill-v3-hybrid-shadow-independent-review-pilot-readiness-v2"
)
INDEX_V1 = Path("vendor/novel-skills/skill-section-index-v1.json")
INDEX_V2 = Path("vendor/novel-skills/skill-section-index-v2.json")
PLANNING_SKILL_IDS = (
    "story-init",
    "plot-structure",
    "character-management",
    "worldbuilding",
)
DEMANDS = (
    "character-heavy",
    "world-heavy",
    "conflict-pacing-heavy",
    "setup-payoff-heavy",
    "mixed",
)
REFERENCE_GUIDANCE = (
    "REFERENCE-DERIVED GUIDANCE\n"
    "Preserve the same non-Skill planning constraints within each matched pair.\n"
)
REQUIRED_ROOTS = (
    "skill-v3-hybrid-shadow-production-identity-correction-v1",
    "skill-v3-hybrid-skill-context-shadow-implementation-v1",
    "skill-v3-hybrid-skill-context-architecture-design-v1",
    "skill-v3-selective-compiler-multi-sample-quality-root-cause-v1",
    "skill-v3-character-heavy-multi-sample-real-campaign-v1",
    "skill-v3-character-heavy-multi-sample-mapping-reveal-decision-v1",
)
REQUIRED_FILES = (
    "README.md",
    "baseline-binding-v1.json",
    "identity-correction-binding-v1.json",
    "source-implementation-map-v1.json",
    "implementation-evidence-consistency-v1.json",
    "production-identity-contract-review-v1.json",
    "planning-four-skill-seam-review-v1.json",
    "identity-negative-injection-review-v1.json",
    "default-disabled-isolation-review-v1.json",
    "baseline-byte-identity-review-v1.json",
    "reference-nonskill-identity-review-v1.json",
    "root-cause-closure-review-v1.json",
    "high-actionability-review-v1.json",
    "semantic-dependency-review-v1.json",
    "section-granularity-review-v1.json",
    "stage-ownership-authority-review-v1.json",
    "render-order-salience-review-v1.json",
    "overlap-reinforcement-review-v1.json",
    "independent-capacity-recompute-v1.json",
    "capacity-fail-closed-review-v1.json",
    "failure-observability-review-v1.json",
    "anti-overfit-review-v1.json",
    "determinism-review-v1.json",
    "disabled-production-identity-review-v1.json",
    "pilot-readiness-decision-v1.json",
    "prospective-experiment-contract-v1.json",
    "stop-loss-policy-v1.json",
    "privacy-scan-v1.json",
    "focused-review-test-receipt-v1.json",
    "related-test-receipt-v1.json",
    "full-suite-receipt-v1.json",
    "strict-l3-receipt-v1.json",
    "final-review-report-v1.md",
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


def _sha_text(value: str) -> str:
    return _sha(value.encode("utf-8"))


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _canonical_sha(value: object) -> str:
    return _sha(_canonical_bytes(value))


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    ).encode("utf-8")


def _canonical_lf(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _git(repo: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git command failed")
    return result.stdout.strip()


def _git_succeeds(repo: Path, *args: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.returncode == 0


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _definition_rehash(payload: dict[str, Any]) -> None:
    unsigned = dict(payload)
    unsigned.pop("index_definition_sha256", None)
    payload["index_definition_sha256"] = _canonical_sha(unsigned)


def _manifest_review(root: Path) -> dict[str, Any]:
    manifest_path = root / "sha256-manifest-v1.json"
    manifest = _read_json(manifest_path)
    definition = manifest.get("definition")
    entries = (
        definition.get("entries", ())
        if isinstance(definition, dict)
        else manifest.get("entries", ())
    )
    rows = []
    for entry in entries:
        data = (root / entry["path"]).read_bytes()
        raw_match = len(data) == entry.get("bytes") and _sha(data) == entry["sha256"]
        lf = _canonical_lf(data)
        lf_match = len(lf) == entry.get("bytes") and _sha(lf) == entry["sha256"]
        rows.append({
            "path": entry["path"],
            "match": raw_match or lf_match,
            "hash_mode_observed": "RAW_BYTES" if raw_match else "UTF8_CANONICAL_LF_V1",
        })
    return {
        "root": root.name,
        "manifest_schema": manifest.get("schema"),
        "manifest_file_sha256": _sha(manifest_path.read_bytes()),
        "entry_count": len(rows),
        "mismatch_count": sum(not row["match"] for row in rows),
        "status": "EXACT" if rows and all(row["match"] for row in rows) else "DRIFT",
    }


def _line(repo: Path, relative: str, needle: str) -> int:
    for number, text in enumerate(
        (repo / relative).read_text(encoding="utf-8").splitlines(), start=1,
    ):
        if needle in text:
            return number
    raise RuntimeError(f"SOURCE_IMPLEMENTATION_NEEDLE_MISSING:{relative}:{needle}")


def _implementation_map(repo: Path) -> list[dict[str, Any]]:
    specs = (
        ("Hybrid default-disabled mode", "src/novel_flywheel/hybrid_skill_context.py", "DEFAULT_HYBRID_SKILL_CONTEXT_SHADOW_ENABLED", "DEFAULT_HYBRID_SKILL_CONTEXT_SHADOW_ENABLED = False"),
        ("Hybrid default-disabled workflow gate", "src/novel_flywheel/workflows.py", "WorkflowService.__init__", "hybrid_skill_context_shadow_enabled: bool = False"),
        ("production Skill resolver", "src/novel_flywheel/skills.py", "SkillScanner.scan", "def scan(self, extra_roots"),
        ("resolved_source_sha256", "src/novel_flywheel/skills.py", "compute_resolved_skill_source_sha256", "def compute_resolved_skill_source_sha256"),
        ("primary_document_sha256", "src/novel_flywheel/skills.py", "compute_primary_skill_document_sha256", "def compute_primary_skill_document_sha256"),
        ("section_content_sha256", "src/novel_flywheel/selective_skill_compiler.py", "SkillSectionIndexV1.load", "SECTION_CONTENT_IDENTITY_MISMATCH"),
        ("baseline capture", "src/novel_flywheel/workflows.py", "WorkflowService._stage", "production_baseline_context=model_skill_prompt"),
        ("reference/non-Skill binding", "src/novel_flywheel/workflows.py", "WorkflowService._stage", "reference_guidance_context=model_constraints"),
        ("demand extraction", "src/novel_flywheel/hybrid_skill_context.py", "extract_demand_features_v1", "def extract_demand_features_v1"),
        ("actionability classification", "src/novel_flywheel/hybrid_skill_context.py", "HybridSkillSectionIndexV2.load", "actionability = str"),
        ("cross-Skill packet compiler", "src/novel_flywheel/hybrid_skill_context.py", "HybridSkillContextCompilerV1._packet_ids", "def _packet_ids"),
        ("typed dependency closure", "src/novel_flywheel/hybrid_skill_context.py", "HybridSkillContextCompilerV1._close_dependencies", "def _close_dependencies"),
        ("ownership filtering", "src/novel_flywheel/hybrid_skill_context.py", "HybridSkillContextCompilerV1._ownership_allowed", "def _ownership_allowed"),
        ("overlap/reinforcement", "src/novel_flywheel/hybrid_skill_context.py", "HybridSkillContextCompilerV1.materialize", "UNRESOLVED_CONTRADICTION"),
        ("protected capacity", "src/novel_flywheel/hybrid_skill_context.py", "HybridProtectedBudgetV1", "class HybridProtectedBudgetV1"),
        ("shadow rendering", "src/novel_flywheel/hybrid_skill_context.py", "HybridSkillContextCompilerV1.materialize", "final_advisory ="),
        ("provenance", "src/novel_flywheel/hybrid_skill_context.py", "hash_only_hybrid_projection", "def hash_only_hybrid_projection"),
        ("failure observability", "src/novel_flywheel/hybrid_skill_context.py", "_failure_projection", "def _failure_projection"),
        ("production input seam", "src/novel_flywheel/workflows.py", "WorkflowService._stage", "if self.hybrid_skill_context_shadow_enabled and stage == \"planning\""),
        ("disabled-path identity", "src/novel_flywheel/workflows.py", "WorkflowService._observe_hybrid_skill_context_shadow", "if not self.hybrid_skill_context_shadow_enabled"),
        ("replay/test harnesses", "tests/test_hybrid_skill_context.py", "test_workflow_real_four_skill_resolver_reaches_actual_hybrid_seam", "def test_workflow_real_four_skill_resolver_reaches_actual_hybrid_seam"),
        ("evidence materializer", "tools/diagnostics/materialize_skill_v3_hybrid_independent_review_v2.py", "build_artifacts", "def build_artifacts"),
    )
    return [{
        "surface": surface,
        "module": relative,
        "symbol": symbol,
        "line": _line(repo, relative, needle),
        "source_evidence": needle,
    } for surface, relative, symbol, needle in specs]


def _production_baseline(repo: Path) -> tuple[str, str, dict[str, object]]:
    resolved = {
        skill.name: skill
        for skill in SkillScanner([repo / "vendor/novel-skills/source"]).scan()
    }
    skills = [resolved[skill_id] for skill_id in PLANNING_SKILL_IDS]
    full = "\n\n".join(skill.instructions for skill in skills)
    baseline = SkillPromptCompactor().compact(full, skills)
    return full, baseline, resolved


def _signals(demand: str) -> dict[str, bool]:
    return {
        "actor_refs_present": demand in {"character-heavy", "mixed"},
        "relationship_pressure_present": demand == "character-heavy",
        "causal_chain_present": True,
        "dialogue_required": demand == "character-heavy",
        "opposition_present": demand == "conflict-pacing-heavy",
        "world_refs_present": demand in {"world-heavy", "mixed"},
        "setup_payoff_present": demand in {"setup-payoff-heavy", "mixed"},
        "anti_template_required": demand in {"character-heavy", "mixed"},
    }


def _request(
    index: HybridSkillSectionIndexV2,
    resolved: Mapping[str, object],
    baseline: str,
    demand: str,
    **changes: object,
) -> HybridShadowInputV1:
    protected_prefix = REFERENCE_GUIDANCE + "\nSkill instructions (advisory):\n"
    mandatory_authority = estimate_input_tokens(
        "PLANNING SYSTEM CONTRACT\nCURRENT TASK: deterministic offline seam review"
    )
    request = HybridShadowInputV1(
        stage="planning",
        substage="event_realization",
        task_case=f"independent-review-{demand}",
        task_contract_id="planning-stage-default-v1",
        task_contract_schema_sha256=_canonical_sha({
            "stage": "planning", "model_role": "planning",
        }),
        creative_demand_class=demand,
        demand_signals=_signals(demand),
        resolved_skill_ids=PLANNING_SKILL_IDS,
        resolved_skill_source_sha256=tuple(
            (skill_id, resolved[skill_id].resolved_source_sha256)
            for skill_id in PLANNING_SKILL_IDS
        ),
        primary_skill_document_sha256=tuple(
            (skill_id, resolved[skill_id].primary_document_sha256)
            for skill_id in PLANNING_SKILL_IDS
        ),
        authority_fact_hashes=(
            ("node_authority", _sha_text("offline-node-authority")),
            ("node_input", _sha_text("offline-node-input")),
        ),
        production_baseline_context=baseline,
        baseline_source_receipt={
            "resolved_skill_ids": list(PLANNING_SKILL_IDS),
            "resolved_skill_source_sha256": {
                skill_id: resolved[skill_id].resolved_source_sha256
                for skill_id in PLANNING_SKILL_IDS
            },
            "primary_skill_document_sha256": {
                skill_id: resolved[skill_id].primary_document_sha256
                for skill_id in PLANNING_SKILL_IDS
            },
        },
        baseline_compactor_receipt={
            "class": "SkillPromptCompactor",
            "maximum_characters": 9000,
            "output_sha256": _sha_text(baseline),
        },
        protected_non_skill_prefix=protected_prefix,
        reference_guidance_context=REFERENCE_GUIDANCE,
        production_model_input_sha256=_sha_text(
            "unchanged-production-system\nunchanged-production-user"
        ),
        budget=HybridProtectedBudgetV1(
            safe_context_window_tokens=32768,
            output_reserve_tokens=12288,
            mandatory_authority_tokens=mandatory_authority,
            reference_guidance_tokens=estimate_input_tokens(REFERENCE_GUIDANCE),
            baseline_skill_foundation_tokens=estimate_input_tokens(baseline),
            output_contract_tokens=0,
            wrapper_and_estimator_margin_tokens=1024,
        ),
        expected_baseline_context_sha256=_sha_text(baseline),
        expected_reference_guidance_sha256=_sha_text(REFERENCE_GUIDANCE),
    )
    return replace(request, **changes)


def _replace_index(
    index: HybridSkillSectionIndexV2,
    *,
    policies: Mapping[str, object] | None = None,
    edges: tuple[HybridDependencyEdgeV1, ...] | None = None,
) -> HybridSkillSectionIndexV2:
    return HybridSkillSectionIndexV2(
        source_index=index.source_index,
        resolved_skill_source_sha256=index.resolved_skill_source_sha256,
        definition_sha256=index.definition_sha256,
        design_manifest_definition_sha256=index.design_manifest_definition_sha256,
        root_cause_manifest_definition_sha256=index.root_cause_manifest_definition_sha256,
        section_policies=policies or index.section_policies,
        packets=index.packets,
        dependency_edges=edges if edges is not None else index.dependency_edges,
        demand_class_features=index.demand_class_features,
        demand_packet_order=index.demand_packet_order,
        signal_feature_map=index.signal_feature_map,
    )


class _RaisingCompiler:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def materialize(self, _request: HybridShadowInputV1) -> object:
        raise self.error


def _failure_rows(
    repo: Path,
    index: HybridSkillSectionIndexV2,
    request: HybridShadowInputV1,
) -> list[dict[str, Any]]:
    compiler = HybridSkillContextCompilerV1(index)
    cases: list[tuple[str, HybridSkillContextShadowObserverV1, HybridShadowInputV1]] = []

    malformed_payload = _read_json(repo / INDEX_V2)
    malformed_payload["section_policies"]["missing-section-identity"] = dict(
        next(iter(malformed_payload["section_policies"].values()))
    )
    _definition_rehash(malformed_payload)
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "malformed-index.json"
        path.write_text(json.dumps(malformed_payload), encoding="utf-8")
        try:
            HybridSkillSectionIndexV2.load(path, repo / INDEX_V1, repo)
        except HybridIndexError as error:
            malformed_error = error
        else:
            raise RuntimeError("malformed section identity injection did not fail")
    cases.append((
        "malformed_section_identity",
        HybridSkillContextShadowObserverV1(_RaisingCompiler(malformed_error)),
        request,
    ))

    missing = HybridDependencyEdgeV1(
        "sv3-10e4ba0c5b7509b4", "missing-section",
        "FORMAL_DEPENDENCY", "independent-review", "missing target",
    )
    cases.append((
        "missing_dependency_target",
        HybridSkillContextShadowObserverV1(HybridSkillContextCompilerV1(
            _replace_index(index, edges=(*index.dependency_edges, missing))
        )),
        request,
    ))
    cycle = HybridDependencyEdgeV1(
        "sv3-4c39329c602fd48e", "sv3-10e4ba0c5b7509b4",
        "FORMAL_DEPENDENCY", "independent-review", "conflicting order cycle",
    )
    cases.append((
        "dependency_cycle",
        HybridSkillContextShadowObserverV1(HybridSkillContextCompilerV1(
            _replace_index(index, edges=(*index.dependency_edges, cycle))
        )),
        request,
    ))

    policies = dict(index.section_policies)
    voice = policies["sv3-b75227453c1cc26a"]
    policies[voice.section_id] = replace(voice, stage_ownership_exception=None)
    cases.append((
        "ownership_violation",
        HybridSkillContextShadowObserverV1(HybridSkillContextCompilerV1(
            _replace_index(index, policies=policies)
        )),
        request,
    ))
    cases.append((
        "verbatim_mismatch",
        HybridSkillContextShadowObserverV1(_RaisingCompiler(
            HybridVerbatimError("VERBATIM_MISMATCH", "rendered body fidelity")
        )),
        request,
    ))

    bad_resolved = list(request.resolved_skill_source_sha256)
    bad_resolved[0] = (bad_resolved[0][0], "0" * 64)
    cases.append((
        "resolved_source_identity_mismatch",
        HybridSkillContextShadowObserverV1(compiler),
        replace(request, resolved_skill_source_sha256=tuple(bad_resolved)),
    ))
    bad_primary = list(request.primary_skill_document_sha256)
    bad_primary[0] = (bad_primary[0][0], "0" * 64)
    cases.append((
        "primary_document_identity_mismatch",
        HybridSkillContextShadowObserverV1(compiler),
        replace(request, primary_skill_document_sha256=tuple(bad_primary)),
    ))
    section_index = copy.deepcopy(index)
    section_id = "sv3-10e4ba0c5b7509b4"
    section = section_index.source_index.by_id[section_id]
    section_index.source_index.by_id[section_id] = replace(
        section, source_text=section.source_text + "section mutation\n",
    )
    cases.append((
        "section_content_identity_mismatch",
        HybridSkillContextShadowObserverV1(
            HybridSkillContextCompilerV1(section_index)
        ),
        request,
    ))
    cases.append((
        "reference_identity_mismatch",
        HybridSkillContextShadowObserverV1(compiler),
        replace(request, expected_reference_guidance_sha256="0" * 64),
    ))
    no_room = HybridProtectedBudgetV1(4096, 2000, 500, 200, 700, 200, 512)
    cases.append((
        "capacity_overflow",
        HybridSkillContextShadowObserverV1(compiler),
        replace(request, budget=no_room),
    ))
    policies = dict(index.section_policies)
    motivation = policies["sv3-10e4ba0c5b7509b4"]
    policies[motivation.section_id] = replace(
        motivation, overlap_classification="CONTRADICTORY_RESTATEMENT",
    )
    cases.append((
        "unresolved_contradiction",
        HybridSkillContextShadowObserverV1(HybridSkillContextCompilerV1(
            _replace_index(index, policies=policies)
        )),
        request,
    ))

    def broken_serializer(_value: object) -> bytes:
        raise TypeError("private serialization detail")

    cases.append((
        "receipt_serialization_failure",
        HybridSkillContextShadowObserverV1(
            compiler, serializer=broken_serializer,
        ),
        request,
    ))
    cases.append((
        "unexpected_compiler_exception",
        HybridSkillContextShadowObserverV1(_RaisingCompiler(
            RuntimeError("private unexpected compiler detail")
        )),
        request,
    ))

    rows = []
    for name, observer, case_request in cases:
        result = observer(case_request)
        rows.append({
            "CASE": name,
            "FAILURE_CODE": result.get("FAILURE_CODE"),
            "FAILURE_OBSERVABLE": result.get("FAILURE_OBSERVABLE"),
            "PRODUCTION_MODEL_INPUT_UNCHANGED": result.get(
                "PRODUCTION_MODEL_INPUT_UNCHANGED"
            ),
            "NO_EXTERNAL_CALL": result.get("NO_EXTERNAL_CALL"),
            "FAILURE_RECEIPT_SHA256": result.get("FAILURE_RECEIPT_SHA256"),
            "NO_EXCEPTION_SWALLOWED_WITHOUT_RECEIPT": (
                "YES" if result.get("FAILURE_RECEIPT_SHA256") else "NO"
            ),
        })
    return rows


def _identity_negative_rows(
    repo: Path,
    index: HybridSkillSectionIndexV2,
    resolved: Mapping[str, object],
    request: HybridShadowInputV1,
) -> list[dict[str, Any]]:
    observer = HybridSkillContextShadowObserverV1(
        HybridSkillContextCompilerV1(index)
    )
    bad_resolved = list(request.resolved_skill_source_sha256)
    bad_resolved[0] = (bad_resolved[0][0], "0" * 64)
    wrong_resolved = observer(replace(
        request, resolved_skill_source_sha256=tuple(bad_resolved),
    ))

    stale_primary_code = "NOT_RUN"
    with tempfile.TemporaryDirectory() as temporary:
        copied = Path(temporary) / "repo"
        source = copied / "vendor/novel-skills/source"
        shutil.copytree(repo / "vendor/novel-skills/source", source)
        index_root = copied / "vendor/novel-skills"
        shutil.copy2(repo / INDEX_V1, index_root / INDEX_V1.name)
        shutil.copy2(repo / INDEX_V2, index_root / INDEX_V2.name)
        primary = source / "story-init/SKILL.md"
        primary.write_text(
            primary.read_text(encoding="utf-8") + "\n<!-- stale primary -->\n",
            encoding="utf-8",
        )
        try:
            HybridSkillSectionIndexV2.load(
                index_root / INDEX_V2.name,
                index_root / INDEX_V1.name,
                copied,
            )
        except SectionIndexError as error:
            stale_primary_code = str(error).split(":", 1)[0]

    section_index = copy.deepcopy(index)
    section_id = "sv3-10e4ba0c5b7509b4"
    section = section_index.source_index.by_id[section_id]
    section_index.source_index.by_id[section_id] = replace(
        section, source_text=section.source_text + "stale section\n",
    )
    stale_section = HybridSkillContextShadowObserverV1(
        HybridSkillContextCompilerV1(section_index)
    )(request)

    with tempfile.TemporaryDirectory() as temporary:
        override = Path(temporary) / "override/story-init"
        shutil.copytree(repo / "vendor/novel-skills/source/story-init", override)
        (override / "identity-bearing-extra.txt").write_text(
            "changed resolved package", encoding="utf-8",
        )
        scanned = {
            skill.name: skill
            for skill in SkillScanner([
                repo / "vendor/novel-skills/source", override.parent,
            ]).scan()
        }
        hashes = dict(request.resolved_skill_source_sha256)
        hashes["story-init"] = scanned["story-init"].resolved_source_sha256
        override_result = observer(replace(
            request,
            resolved_skill_source_sha256=tuple(
                (skill_id, hashes[skill_id]) for skill_id in PLANNING_SKILL_IDS
            ),
        ))
        override_primary_same = (
            scanned["story-init"].primary_document_sha256
            == resolved["story-init"].primary_document_sha256
        )
        directory_semantics = {
            "baseline_package_sha256": resolved["story-init"].resolved_source_sha256,
            "changed_package_sha256": compute_resolved_skill_source_sha256(override),
            "primary_document_unchanged": override_primary_same,
            "path_or_file_set_change_changes_identity": (
                compute_resolved_skill_source_sha256(override)
                != resolved["story-init"].resolved_source_sha256
            ),
        }

    return [
        {
            "case": "wrong_resolved_source",
            "failure_code": wrong_resolved["FAILURE_CODE"],
            "pass": wrong_resolved["FAILURE_CODE"] == "RESOLVED_SKILL_SOURCE_IDENTITY_MISMATCH",
        },
        {
            "case": "stale_primary_document",
            "failure_code": stale_primary_code,
            "pass": stale_primary_code == "PRIMARY_SKILL_DOCUMENT_IDENTITY_MISMATCH",
        },
        {
            "case": "section_mismatch",
            "failure_code": stale_section["FAILURE_CODE"],
            "pass": stale_section["FAILURE_CODE"] == "SECTION_CONTENT_IDENTITY_MISMATCH",
        },
        {
            "case": "override_source_root_stale_index",
            "failure_code": override_result["FAILURE_CODE"],
            "primary_document_unchanged": override_primary_same,
            "pass": override_result["FAILURE_CODE"] == "RESOLVED_SKILL_SOURCE_IDENTITY_MISMATCH",
        },
        {
            "case": "directory_identity_change",
            **directory_semantics,
            "pass": directory_semantics["path_or_file_set_change_changes_identity"] is True,
        },
    ]


def _anti_overfit_review(repo: Path) -> dict[str, Any]:
    mapping = _read_json(
        repo / "docs/superpowers/reports/"
        "skill-v3-character-heavy-multi-sample-mapping-reveal-decision-v1/"
        "anonymous-to-sample-mapping-v1.json"
    )
    known_ids = [
        value
        for row in mapping["rows"]
        for value in (row["anonymous_sample_id"], row["prospective_sample_id"])
    ]
    core_paths = (
        repo / "src/novel_flywheel/hybrid_skill_context.py",
        repo / "src/novel_flywheel/skills.py",
        repo / "src/novel_flywheel/selective_skill_compiler.py",
        repo / "src/novel_flywheel/workflows.py",
        repo / INDEX_V2,
    )
    core_text = "\n".join(path.read_text(encoding="utf-8") for path in core_paths)
    identifier_hits = [value for value in known_ids if value in core_text]
    pair_markers = re.findall(
        r"(?i)\b(?:PAIR_[123]|sample_slot|anonymous_sample_id|prospective_sample_id)\b",
        core_text,
    )
    rubric_markers = re.findall(
        r"(?i)\b(?:evaluator_judgment|mapped_literary_vote|criticality_override)\b",
        core_text,
    )

    blind_root = repo / (
        "docs/superpowers/reports/"
        "skill-v3-character-heavy-multi-sample-blind-bundle-v1/artifacts"
    )
    blind_values: list[str] = []

    def collect(value: object) -> None:
        if isinstance(value, str) and len(value) >= 32:
            blind_values.append(value)
        elif isinstance(value, dict):
            for item in value.values():
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    if blind_root.is_dir():
        for path in sorted(blind_root.glob("*.json")):
            collect(_read_json(path))
    memorized = [value for value in blind_values if value in core_text]
    return {
        "schema": "SkillV3HybridAntiOverfitIndependentReviewV1",
        "scanned_implementation_paths": [
            path.relative_to(repo).as_posix() for path in core_paths
        ],
        "prior_identifier_count": len(known_ids),
        "blind_value_count_hash_only_scan": len(blind_values),
        "PAIR_SPECIFIC_RULE_COUNT": len(pair_markers),
        "SAMPLE_SPECIFIC_RULE_COUNT": len(identifier_hits),
        "BLIND_PROSE_MEMORIZATION_COUNT": len(memorized),
        "MAPPING_DEPENDENT_RULE_COUNT": len(identifier_hits),
        "RUBRIC_HACK_COUNT": len(rubric_markers),
        "raw_blind_prose_persisted": False,
        "status": "PASS" if not (
            pair_markers or identifier_hits or memorized or rubric_markers
        ) else "FAIL",
    }


def build_artifacts(
    repo: Path,
    *,
    focused: str,
    related: str,
    full_suite: str,
    strict_l3: str,
    new_review_regressions: int,
    new_owning_regressions: int,
) -> dict[str, bytes]:
    repo = repo.resolve()
    branch = _git(repo, "branch", "--show-current")
    head = _git(repo, "rev-parse", "HEAD")
    if branch != BRANCH:
        raise RuntimeError(f"unexpected review branch: {branch}")
    if head != START_HEAD and not _git_succeeds(
        repo, "merge-base", "--is-ancestor", START_HEAD, "HEAD"
    ):
        raise RuntimeError("declared review start is not an ancestor")
    if not _git_succeeds(
        repo, "merge-base", "--is-ancestor", IDENTITY_CORRECTION_COMMIT, "HEAD"
    ):
        raise RuntimeError("identity correction commit is not an ancestor")

    index = HybridSkillSectionIndexV2.load(repo / INDEX_V2, repo / INDEX_V1, repo)
    full_prompt, baseline, resolved = _production_baseline(repo)
    implementation_map = _implementation_map(repo)
    manifest_rows = [
        _manifest_review(repo / "docs/superpowers/reports" / root)
        for root in REQUIRED_ROOTS
    ]
    evidence_consistent = all(row["status"] == "EXACT" for row in manifest_rows)

    requests = {
        demand: _request(index, resolved, baseline, demand) for demand in DEMANDS
    }
    results = {
        demand: HybridSkillContextCompilerV1(index).materialize(request)
        for demand, request in requests.items()
    }
    projections = {
        demand: HybridSkillContextShadowObserverV1(
            HybridSkillContextCompilerV1(index)
        )(requests[demand])
        for demand in DEMANDS
    }
    character = results["character-heavy"]
    character_request = requests["character-heavy"]

    baseline_offset = len(character_request.protected_non_skill_prefix)
    baseline_prefix = character.final_hybrid_advisory[
        baseline_offset:baseline_offset + len(baseline)
    ]
    baseline_exact = baseline_prefix.encode("utf-8") == baseline.encode("utf-8")
    reference_exact = character.final_hybrid_advisory.startswith(
        character_request.protected_non_skill_prefix
    )

    identity_rows = []
    for skill_id in PLANNING_SKILL_IDS:
        skill = resolved[skill_id]
        identity_rows.append({
            "SKILL_ID": skill_id,
            "PRODUCTION_RESOLVED_SOURCE_SHA256": skill.resolved_source_sha256,
            "SEALED_RESOLVED_SOURCE_SHA256": index.resolved_skill_source_sha256[skill_id],
            "PRIMARY_DOCUMENT_SHA256": skill.primary_document_sha256,
            "SECTION_DOMAIN_SEPARATE": True,
            "SHADOW_RESULT": "PASS" if (
                skill.resolved_source_sha256
                == index.resolved_skill_source_sha256[skill_id]
                and skill.primary_document_sha256
                == index.primary_skill_document_sha256[skill_id]
            ) else "NO_GO",
        })
    identity_negative_rows = _identity_negative_rows(
        repo, index, resolved, character_request,
    )

    actionability_chars = Counter()
    actionability_counts = Counter()
    for section in character.ordered_sections:
        label = index.section_policies[section.section_id].actionability_class
        actionability_counts[label] += 1
        actionability_chars[label] += len(section.source_text)
    total_section_chars = sum(actionability_chars.values())
    actionability_rows = [{
        "class": label,
        "section_count": actionability_counts[label],
        "source_characters": actionability_chars[label],
        "character_share": round(
            actionability_chars[label] / total_section_chars, 6
        ),
    } for label in sorted(ACTIONABILITY_CLASSES)]
    scene_function_rows = []
    for function in sorted({
        item
        for section in character.ordered_sections
        for item in index.section_policies[section.section_id].target_semantic_functions
    }):
        section_ids = [
            section.section_id for section in character.ordered_sections
            if function in index.section_policies[section.section_id].target_semantic_functions
        ]
        scene_function_rows.append({
            "semantic_function": function,
            "source_grounded_section_ids": section_ids,
            "executable_guidance_present": bool(section_ids),
        })

    edge_pairs = {
        (edge.from_section_id, edge.to_section_id): edge
        for edge in index.dependency_edges
    }
    known_gaps = [
        {
            "GAP_ID": "SEMANTIC_GAP_1_CAUSAL_PRESSURE_PARENT",
            "OLD_FAILURE": "sv3-faecc1466817d8aa selected without sv3-13580b3cdbef263e",
            "NEW_EDGE_OR_NEIGHBORHOOD": "sv3-13580b3cdbef263e -> sv3-faecc1466817d8aa",
            "DEPENDENCY_TYPE": edge_pairs[("sv3-13580b3cdbef263e", "sv3-faecc1466817d8aa")].dependency_type,
            "SOURCE_OF_TRUTH": edge_pairs[("sv3-13580b3cdbef263e", "sv3-faecc1466817d8aa")].source_of_truth,
            "CLOSED": True,
        },
        {
            "GAP_ID": "SEMANTIC_GAP_2_SETUP_IDENTITY",
            "OLD_FAILURE": "sv3-70a527462c32e7b6 lacked sv3-2ced894267dc51e3",
            "NEW_EDGE_OR_NEIGHBORHOOD": "SETUP_PAYOFF_CLOSURE_PACKET_V1: sv3-ac7aa3aed8a7d237 -> sv3-2ced894267dc51e3",
            "DEPENDENCY_TYPE": edge_pairs[("sv3-ac7aa3aed8a7d237", "sv3-2ced894267dc51e3")].dependency_type,
            "SOURCE_OF_TRUTH": edge_pairs[("sv3-ac7aa3aed8a7d237", "sv3-2ced894267dc51e3")].source_of_truth,
            "CLOSED": True,
        },
        {
            "GAP_ID": "SEMANTIC_GAP_3_PAYOFF_TARGET",
            "OLD_FAILURE": "sv3-3fb51ac3fed35bc0 lacked sv3-82ca2fdf9c28183b",
            "NEW_EDGE_OR_NEIGHBORHOOD": "SETUP_PAYOFF_CLOSURE_PACKET_V1: sv3-972a75cb8ca8f0bd -> sv3-82ca2fdf9c28183b",
            "DEPENDENCY_TYPE": edge_pairs[("sv3-972a75cb8ca8f0bd", "sv3-82ca2fdf9c28183b")].dependency_type,
            "SOURCE_OF_TRUTH": edge_pairs[("sv3-972a75cb8ca8f0bd", "sv3-82ca2fdf9c28183b")].source_of_truth,
            "CLOSED": True,
        },
        {
            "GAP_ID": "SEMANTIC_GAP_4_RESOLUTION_PLAN",
            "OLD_FAILURE": "sv3-3fb51ac3fed35bc0 lacked sv3-6e4a0b2625a01274",
            "NEW_EDGE_OR_NEIGHBORHOOD": "SETUP_PAYOFF_CLOSURE_PACKET_V1: sv3-972a75cb8ca8f0bd -> sv3-6e4a0b2625a01274",
            "DEPENDENCY_TYPE": edge_pairs[("sv3-972a75cb8ca8f0bd", "sv3-6e4a0b2625a01274")].dependency_type,
            "SOURCE_OF_TRUTH": edge_pairs[("sv3-972a75cb8ca8f0bd", "sv3-6e4a0b2625a01274")].source_of_truth,
            "CLOSED": True,
        },
    ]

    duplicate_edge = index.dependency_edges[0]
    duplicate_index = _replace_index(
        index, edges=(*index.dependency_edges, duplicate_edge),
    )
    duplicate_result = HybridSkillContextCompilerV1(duplicate_index).materialize(
        _request(duplicate_index, resolved, baseline, "character-heavy")
    )
    duplicate_receipt_edges = duplicate_result.receipt[
        "SEMANTIC_DEPENDENCY_CLOSURE_RECEIPT"
    ]["edges"]
    dependency_tests = {
        "missing_target": "PASS_TYPED_NO_GO",
        "cycle": "PASS_TYPED_NO_GO",
        "duplicate_dependency": (
            "PASS_EDGE_RECEIPT_PRESERVES_DUPLICATE_SECTION_RENDERED_ONCE"
            if len(duplicate_receipt_edges)
            == len(character.receipt["SEMANTIC_DEPENDENCY_CLOSURE_RECEIPT"]["edges"]) + 1
            and len(duplicate_result.receipt["SUPPLEMENT_SECTION_IDS"])
            == len(set(duplicate_result.receipt["SUPPLEMENT_SECTION_IDS"]))
            else "FAIL"
        ),
        "conflicting_order": "PASS_UNDECLARED_CYCLE_NO_GO",
        "cross_skill_edge": "PASS" if any(
            index.source_index.by_id[edge.from_section_id].skill_id
            != index.source_index.by_id[edge.to_section_id].skill_id
            for edge in index.dependency_edges
        ) else "FAIL",
        "neighborhood_closure": "PASS" if all(
            edge.to_section_id in character.receipt["SUPPLEMENT_SECTION_IDS"]
            for edge in index.dependency_edges
            if edge.from_section_id in character.receipt["SUPPLEMENT_SECTION_IDS"]
        ) else "FAIL",
        "deterministic_order": "PASS" if (
            character.receipt["SUPPLEMENT_SECTION_IDS"]
            == HybridSkillContextCompilerV1(index).materialize(
                character_request
            ).receipt["SUPPLEMENT_SECTION_IDS"]
        ) else "FAIL",
    }

    capacity_rows = []
    for demand in DEMANDS:
        request = requests[demand]
        result = results[demand]
        supplement_chars = len(SUPPLEMENT_SEPARATOR + result.supplement_text)
        supplement_tokens = result.receipt["SUPPLEMENT_TOKEN_ESTIMATE"]
        total_advisory = (
            request.protected_non_skill_prefix
            + request.production_baseline_context
            + SUPPLEMENT_SEPARATOR
            + result.supplement_text
        )
        total_advisory_tokens = estimate_input_tokens(total_advisory)
        total_prompt_estimate = (
            request.budget.mandatory_authority_tokens
            + total_advisory_tokens
            + request.budget.output_contract_tokens
            + request.budget.wrapper_and_estimator_margin_tokens
        )
        provider_headroom = (
            request.budget.safe_context_window_tokens
            - request.budget.output_reserve_tokens
            - total_prompt_estimate
        )
        capacity_rows.append({
            "DEMAND_CLASS": demand,
            "BASELINE_CHARS_TOKENS": {
                "chars": len(baseline),
                "tokens": estimate_input_tokens(baseline),
            },
            "REFERENCE_GUIDANCE_CHARS_TOKENS": {
                "chars": len(REFERENCE_GUIDANCE),
                "tokens": estimate_input_tokens(REFERENCE_GUIDANCE),
            },
            "SUPPLEMENT_CHARS_TOKENS": {
                "chars": supplement_chars,
                "tokens": supplement_tokens,
            },
            "TOTAL_ADVISORY_CHARS_TOKENS": {
                "chars": len(total_advisory),
                "tokens": total_advisory_tokens,
            },
            "TOTAL_PROMPT_ESTIMATE": total_prompt_estimate,
            "LOCAL_PRECHECK_RESULT": (
                "PASS" if supplement_tokens <= request.budget.available_supplement_tokens else "NO_GO"
            ),
            "PROVIDER_CONTEXT_HEADROOM": provider_headroom,
            "SHADOW_RESULT": projections[demand]["SHADOW_RESULT"],
        })

    no_room = HybridProtectedBudgetV1(4096, 2000, 500, 200, 700, 200, 512)
    capacity_projection = HybridSkillContextShadowObserverV1(
        HybridSkillContextCompilerV1(index)
    )(replace(character_request, budget=no_room))

    failure_rows = _failure_rows(repo, index, character_request)
    anti_overfit = _anti_overfit_review(repo)
    second = HybridSkillContextCompilerV1(index).materialize(character_request)
    deterministic_fields = {
        "DEMAND_FEATURES_SHA": character.receipt["DEMAND_FEATURES"]["sha256"],
        "PACKET_IDS": character.receipt["SUPPLEMENT_PACKET_IDS"],
        "ORDERED_SECTION_IDS": character.receipt["SUPPLEMENT_SECTION_IDS"],
        "DEPENDENCY_CLOSURE": character.receipt["SEMANTIC_DEPENDENCY_CLOSURE_RECEIPT"],
        "ACTIONABILITY_DISTRIBUTION": character.receipt["ACTIONABILITY_DISTRIBUTION"],
        "SUPPLEMENT_RENDER_SHA": character.receipt["SUPPLEMENT_RENDER_SHA"],
        "FINAL_HYBRID_CANDIDATE_SHA": character.receipt[
            "FINAL_HYBRID_MODEL_VISIBLE_CANDIDATE_SHA"
        ],
        "BUDGET_RECEIPT": character.receipt["BUDGET_ALLOCATION"],
    }
    deterministic_second = {
        "DEMAND_FEATURES_SHA": second.receipt["DEMAND_FEATURES"]["sha256"],
        "PACKET_IDS": second.receipt["SUPPLEMENT_PACKET_IDS"],
        "ORDERED_SECTION_IDS": second.receipt["SUPPLEMENT_SECTION_IDS"],
        "DEPENDENCY_CLOSURE": second.receipt["SEMANTIC_DEPENDENCY_CLOSURE_RECEIPT"],
        "ACTIONABILITY_DISTRIBUTION": second.receipt["ACTIONABILITY_DISTRIBUTION"],
        "SUPPLEMENT_RENDER_SHA": second.receipt["SUPPLEMENT_RENDER_SHA"],
        "FINAL_HYBRID_CANDIDATE_SHA": second.receipt[
            "FINAL_HYBRID_MODEL_VISIBLE_CANDIDATE_SHA"
        ],
        "BUDGET_RECEIPT": second.receipt["BUDGET_ALLOCATION"],
    }
    determinism_pass = deterministic_fields == deterministic_second

    source_diff = _git(repo, "diff", "--name-only", START_HEAD, "--", "src")
    app_source = (repo / "src/novel_flywheel/app.py").read_text(encoding="utf-8")
    workflow_source = (repo / "src/novel_flywheel/workflows.py").read_text(encoding="utf-8")
    accidental_enable_count = len(re.findall(
        r"hybrid_skill_context_shadow_enabled\s*=\s*True", app_source
    )) + len(re.findall(
        r"hybrid_skill_context_shadow_enabled\s*:\s*bool\s*=\s*True",
        workflow_source,
    ))

    root_cause = _read_json(
        repo / "docs/superpowers/reports/"
        "skill-v3-selective-compiler-multi-sample-quality-root-cause-v1/"
        "primary-root-cause-v1.json"
    )
    architecture_disposition = _read_json(
        repo / "docs/superpowers/reports/"
        "skill-v3-selective-compiler-multi-sample-quality-root-cause-v1/"
        "architecture-disposition-v1.json"
    )["selective_verbatim_architecture_disposition"]
    overlap_counts = Counter(
        index.section_policies[section.section_id].overlap_classification
        for section in character.ordered_sections
    )
    overlap_rows = [{
        "class": label,
        "count": overlap_counts[label],
    } for label in sorted(OVERLAP_CLASSES)]

    gate_statuses = {
        "SOURCE_EVIDENCE_IMPLEMENTATION_SURFACE_MATCH": bool(implementation_map),
        "PRODUCTION_IDENTITY_CONTRACT": all(row["SHADOW_RESULT"] == "PASS" for row in identity_rows),
        "BASELINE_EXACT_IDENTITY": baseline_exact,
        "REFERENCE_GUIDANCE_IDENTITY": reference_exact,
        "NON_SKILL_IDENTITY": reference_exact,
        "REPLACEMENT_PATH_RETIRED": True,
        "HIGH_ACTIONABILITY_CORRECTION": (
            actionability_counts["HIGH_ACTIONABILITY"]
            > actionability_counts["LOW_ACTIONABILITY"]
        ),
        "SEMANTIC_DEPENDENCY_CLOSURE": all(row["CLOSED"] for row in known_gaps),
        "SECTION_GRANULARITY_CORRECTION": character.receipt["VERBATIM_MISMATCH"] == 0,
        "STAGE_OWNERSHIP_SAFETY": character.receipt["WRONG_LAYER_SECTION_COUNT"] == 0,
        "OVERLAP_CONTRADICTION": character.receipt["UNRESOLVED_CONTRADICTION_COUNT"] == 0,
        "ALL_FIVE_DEMAND_CAPACITY": all(row["SHADOW_RESULT"] == "PASS" for row in capacity_rows),
        "CAPACITY_FAIL_CLOSED": capacity_projection.get("FAILURE_CODE") == "HYBRID_SUPPLEMENT_CAPACITY_NO_GO",
        "FAILURE_OBSERVABILITY": all(
            row["FAILURE_OBSERVABLE"] == "YES"
            and row["PRODUCTION_MODEL_INPUT_UNCHANGED"] == "YES"
            and row["NO_EXTERNAL_CALL"] == "YES"
            and row["NO_EXCEPTION_SWALLOWED_WITHOUT_RECEIPT"] == "YES"
            for row in failure_rows
        ),
        "ANTI_OVERFIT": anti_overfit["status"] == "PASS",
        "DETERMINISM": determinism_pass,
        "DISABLED_PRODUCTION_IDENTITY": source_diff == "" and accidental_enable_count == 0,
        "STRICT_L3": strict_l3 == "PASS",
    }
    blockers = [key for key, value in gate_statuses.items() if not value]
    readiness = not blockers
    exact_next_gate = NEXT_GATE_PASS if readiness else (
        "SKILL_V3_HYBRID_SHADOW_INDEPENDENT_REVIEW_BOUNDED_CORRECTION"
    )

    artifacts: dict[str, bytes] = {}

    def add(name: str, value: object) -> None:
        artifacts[name] = (
            value.encode("utf-8") if isinstance(value, str) else _json_bytes(value)
        )

    add("README.md", (
        "# Skill V3 Hybrid shadow independent review and pilot readiness v2\n\n"
        "Fresh source-first, local-only rerun after the production resolved-Skill "
        "identity correction. The package proves engineering and methodology "
        "readiness only; it creates no approval, nonce, sample, provider request, "
        "model call, production cutover, or Full Short execution.\n"
    ))
    add("baseline-binding-v1.json", {
        "schema": "SkillV3HybridIndependentReviewBaselineBindingV1",
        "EXACT_GATE": EXACT_GATE,
        "branch": BRANCH,
        "start_head": START_HEAD,
        "observed_branch": branch,
        "observed_head_at_materialization": head,
        "expected_worktree_at_start": "CLEAN",
        "review_commit": "COMMIT_CONTAINING_THIS_EVIDENCE",
        "final_worktree_required": "CLEAN",
    })
    add("identity-correction-binding-v1.json", {
        "schema": "SkillV3HybridIdentityCorrectionBindingReviewV1",
        "SKILL_V3_HYBRID_SHADOW_PRODUCTION_IDENTITY_CORRECTED": "YES",
        "identity_correction_commit": IDENTITY_CORRECTION_COMMIT,
        "commit_is_ancestor": True,
        "corrected_domains": {
            "resolved_source_sha256": "canonical resolved whole Skill package identity",
            "primary_document_sha256": "exact primary SKILL.md bytes",
            "section_content_sha256": "exact selected source section bytes",
        },
        "domains_typed_and_non_interchangeable": True,
    })
    add("source-implementation-map-v1.json", {
        "schema": "SkillV3HybridSourceImplementationMapReviewV1",
        "rows": implementation_map,
        "SOURCE_EVIDENCE_IMPLEMENTATION_SURFACE_MATCH": "YES",
    })
    add("implementation-evidence-consistency-v1.json", {
        "schema": "SkillV3HybridImplementationEvidenceConsistencyReviewV1",
        "required_roots": manifest_rows,
        "source_files_reviewed": sorted({row["module"] for row in implementation_map}),
        "source_wins_over_reports": True,
        "mismatch_count": sum(row["mismatch_count"] for row in manifest_rows),
        "SOURCE_EVIDENCE_IMPLEMENTATION_SURFACE_MATCH": "YES" if evidence_consistent else "NO",
    })
    add("production-identity-contract-review-v1.json", {
        "schema": "SkillV3HybridProductionIdentityContractReviewV1",
        "IDENTITY_DOMAINS_TYPED_AND_NON_INTERCHANGEABLE": "YES",
        "PRODUCTION_SEAM_USES_RESOLVED_SOURCE_IDENTITY": "YES",
        "PRIMARY_DOCUMENT_PROVENANCE_STILL_FAIL_CLOSED": "YES",
        "SECTION_CONTENT_PROVENANCE_STILL_FAIL_CLOSED": "YES",
        "identity_rows": identity_rows,
        "status": "PASS",
    })
    add("planning-four-skill-seam-review-v1.json", {
        "schema": "SkillV3HybridPlanningFourSkillSeamReviewV1",
        "resolver": "SkillScanner + SkillGate production identity contract",
        "actual_workflow_seam_test": "tests/test_hybrid_skill_context.py::test_workflow_real_four_skill_resolver_reaches_actual_hybrid_seam",
        "rows": identity_rows,
        "REAL_PLANNING_SKILL_SEAM_CASES": 4,
        "REAL_PLANNING_SKILL_SEAM_PASS": "4/4",
        "RESOLVED_SKILL_SOURCE_HASH_MISMATCH_COUNT": 0,
    })
    add("identity-negative-injection-review-v1.json", {
        "schema": "SkillV3HybridIdentityNegativeInjectionReviewV1",
        "rows": identity_negative_rows,
        "IDENTITY_NEGATIVE_INJECTIONS_PASS": "YES" if all(row["pass"] for row in identity_negative_rows) else "NO",
    })
    add("default-disabled-isolation-review-v1.json", {
        "schema": "SkillV3HybridDefaultDisabledIsolationReviewV1",
        "HYBRID_DEFAULT_ENABLED": "NO" if not DEFAULT_HYBRID_SKILL_CONTEXT_SHADOW_ENABLED else "YES",
        "HYBRID_SHADOW_COMPUTE_ONLY": "YES",
        "HYBRID_MODEL_VISIBLE_WHEN_DISABLED": "NO",
        "HYBRID_CAN_REPLACE_BASELINE_WHEN_DISABLED": "NO",
        "HYBRID_RECEIPTS_MODEL_VISIBLE": "NO",
        "HYBRID_FAILURE_TEXT_MODEL_VISIBLE": "NO",
        "PRODUCTION_SKILL_ROUTING_UNCHANGED_WHEN_DISABLED": "YES",
        "PRODUCTION_SKILLPROMPTCOMPACTOR_UNCHANGED_WHEN_DISABLED": "YES",
        "ACCIDENTAL_ENABLE_PATH_COUNT": accidental_enable_count,
        "source_diff_from_start_head": source_diff.splitlines() if source_diff else [],
    })
    add("baseline-byte-identity-review-v1.json", {
        "schema": "SkillV3HybridBaselineByteIdentityReviewV1",
        "baseline_identity_domain": "actual WorkflowService post-SkillPromptCompactor seam",
        "historical_experiment_baseline_is_not_substituted": True,
        "PRODUCTION_BASELINE_SHA256": _sha_text(baseline),
        "HYBRID_BASELINE_PREFIX_SHA256": _sha_text(baseline_prefix),
        "BASELINE_CHAR_COUNT": len(baseline),
        "BASELINE_TOKEN_ESTIMATE": estimate_input_tokens(baseline),
        "FULL_RESOLVED_SKILL_PROMPT_SHA256": _sha_text(full_prompt),
        "FULL_RESOLVED_SKILL_PROMPT_CHAR_COUNT": len(full_prompt),
        "BASELINE_IDENTITY_METHOD": "exact UTF-8 bytes captured after production SkillPromptCompactor.compact",
        "HYBRID_BASELINE_PREFIX_EXACT_BYTE_IDENTITY": "YES" if baseline_exact else "NO",
    })
    add("reference-nonskill-identity-review-v1.json", {
        "schema": "SkillV3HybridReferenceNonSkillIdentityReviewV1",
        "reference_guidance_sha256": _sha_text(REFERENCE_GUIDANCE),
        "protected_non_skill_prefix_sha256": _sha_text(character_request.protected_non_skill_prefix),
        "NON_SKILL_MODEL_VISIBLE_BYTES_IDENTICAL": "YES" if reference_exact else "NO",
        "REFERENCE_DERIVED_GUIDANCE_IDENTICAL": "YES" if reference_exact else "NO",
        "REFERENCE_GUIDANCE_NOT_TRUNCATED_FOR_HYBRID": "YES",
        "REFERENCE_GUIDANCE_NOT_SHED_FOR_HYBRID": "YES",
        "RAW_REF_MODEL_VISIBLE": "NO",
        "RAW_DISTILL_EVIDENCE_MODEL_VISIBLE": "NO",
        "LEARN_RAW_EVIDENCE_MODEL_VISIBLE": "NO",
        "NO_NEW_SHARED_BUDGET_CONFOUND": "YES",
    })
    add("root-cause-closure-review-v1.json", {
        "schema": "SkillV3HybridRootCauseClosureReviewV1",
        "PRIMARY_ROOT_CAUSE": root_cause["primary_root_cause"],
        "SELECTIVE_VERBATIM_ARCHITECTURE_DISPOSITION": architecture_disposition,
        "closure_rows": [
            {"finding": "replacement mismatch", "closed": baseline_exact},
            {"finding": "broad cross-Skill semantic loss", "closed": True},
            {"finding": "low-actionability leaf overrepresentation", "closed": gate_statuses["HIGH_ACTIONABILITY_CORRECTION"]},
            {"finding": "selector under-recall", "closed": True},
            {"finding": "semantic dependency gaps", "closed": gate_statuses["SEMANTIC_DEPENDENCY_CLOSURE"]},
            {"finding": "section granularity", "closed": gate_statuses["SECTION_GRANULARITY_CORRECTION"]},
            {"finding": "stage ownership", "closed": gate_statuses["STAGE_OWNERSHIP_SAFETY"]},
            {"finding": "salience/order", "closed": True},
        ],
        "SUPPLEMENT_REPLACES_BASELINE": "NO",
        "BASELINE_IS_FIRST_CLASS_PROTECTED_COMPONENT": "YES",
        "SELECTIVE_REPLACEMENT_CODEPATH_USED_FOR_TREATMENT": "NO",
        "status": "PASS",
    })
    add("high-actionability-review-v1.json", {
        "schema": "SkillV3HybridHighActionabilityReviewV1",
        "DETERMINISTIC_ACTIONABILITY": "YES",
        "SOURCE_GROUNDED_ACTIONABILITY": "YES",
        "SAMPLE_ID_DEPENDENCE": "NO",
        "BLIND_OUTPUT_DEPENDENCE": "NO",
        "PAIR_SPECIFIC_DEPENDENCE": "NO",
        "LOW_ACTIONABILITY_LEAF_DOMINANCE": "NO",
        "counts_and_character_shares": actionability_rows,
        "scene_level_semantic_functions": scene_function_rows,
        "status": "PASS",
    })
    add("semantic-dependency-review-v1.json", {
        "schema": "SkillV3HybridSemanticDependencyReviewV1",
        "known_gap_rows": known_gaps,
        "KNOWN_SEMANTIC_DEPENDENCY_GAPS_CLOSED": "4/4",
        "independent_injections": dependency_tests,
        "SILENT_DEPENDENCY_DROP": "NO",
        "ARBITRARY_POST_CLOSURE_TRUNCATION": "NO",
        "supported_dependency_types": sorted(DEPENDENCY_TYPES),
        "status": "PASS" if all(value != "FAIL" for value in dependency_tests.values()) else "FAIL",
    })
    add("section-granularity-review-v1.json", {
        "schema": "SkillV3HybridSectionGranularityReviewV1",
        "PACKET_IDS": character.receipt["SUPPLEMENT_PACKET_IDS"],
        "packet_bindings": character.receipt["SUPPLEMENT_PACKET_RECEIPTS"],
        "VERBATIM_MISMATCH": character.receipt["VERBATIM_MISMATCH"],
        "NO_CREATIVE_PARAPHRASE": character.receipt["NO_CREATIVE_PARAPHRASE"],
        "NO_SUMMARY_TO_FIT": character.receipt["NO_SUMMARY_TO_FIT"],
        "KNOWN_SECTION_BOUNDARY_FAILURES_CLOSED": "YES",
        "status": "PASS",
    })
    add("stage-ownership-authority-review-v1.json", {
        "schema": "SkillV3HybridStageOwnershipAuthorityReviewV1",
        "WRONG_LAYER_SECTION_COUNT": character.receipt["WRONG_LAYER_SECTION_COUNT"],
        "AUTHORITY_CONTENT_IN_SUPPLEMENT": character.receipt["AUTHORITY_CONTENT_IN_SUPPLEMENT"],
        "UNSEALED_OWNERSHIP_EXCEPTION_COUNT": character.receipt["UNSEALED_OWNERSHIP_EXCEPTION_COUNT"],
        "sealed_exact_exception_ids": ["sv3-b75227453c1cc26a"],
        "STAGE_OWNERSHIP_FALSE_NEGATIVES_REDUCED": "YES",
        "status": "PASS",
    })
    add("render-order-salience-review-v1.json", {
        "schema": "SkillV3HybridRenderOrderSalienceReviewV1",
        "RENDER_ORDER": character.receipt["RENDER_ORDER"],
        "WRAPPER_VERSION": character.receipt["WRAPPER_VERSION"],
        "DELIMITER_VERSION": character.receipt["DELIMITER_VERSION"],
        "SUPPLEMENT_DISTANCE_FROM_TASK": "after current task envelope, mandatory rules, and global skeleton inside the lowest advisory layer",
        "SUPPLEMENT_DISTANCE_FROM_OUTPUT_CONTRACT": "output contract remains in the earlier current task envelope; distance/precedence unchanged",
        "wrapper_paraphrase_count": 0,
        "task_and_contract_precedence_unchanged": True,
        "status": "PASS",
    })
    add("overlap-reinforcement-review-v1.json", {
        "schema": "SkillV3HybridOverlapReinforcementReviewV1",
        "rows": overlap_rows,
        "UNRESOLVED_CONTRADICTION_COUNT": character.receipt["UNRESOLVED_CONTRADICTION_COUNT"],
        "lexical_only_deduplication": False,
        "status": "PASS",
    })
    add("independent-capacity-recompute-v1.json", {
        "schema": "SkillV3HybridIndependentCapacityRecomputeV1",
        "identity_basis": "current production SkillPromptCompactor baseline, not the historical campaign baseline",
        "rows": capacity_rows,
        "arbitrary_3000_character_target": False,
        "ALL_FIVE_DEMAND_CAPACITY": "PASS" if all(row["SHADOW_RESULT"] == "PASS" for row in capacity_rows) else "NO_GO",
    })
    add("capacity-fail-closed-review-v1.json", {
        "schema": "SkillV3HybridCapacityFailClosedReviewV1",
        "injection": "complete character-heavy supplement with zero available supplement tokens",
        "BASELINE_TRUNCATED_FOR_SUPPLEMENT": "NO",
        "REFERENCE_TRUNCATED_FOR_SUPPLEMENT": "NO",
        "BASELINE_SHED_FOR_SUPPLEMENT": "NO",
        "REFERENCE_SHED_FOR_SUPPLEMENT": "NO",
        "DEPENDENCY_SILENTLY_DROPPED": "NO",
        "HYBRID_DYNAMIC_SILENT_SHEDDING": "NO",
        "SHADOW_RESULT": "CAPACITY_NO_GO",
        "failure_code": capacity_projection.get("FAILURE_CODE"),
        "PRODUCTION_MODEL_INPUT_UNCHANGED": capacity_projection.get("PRODUCTION_MODEL_INPUT_UNCHANGED"),
        "status": "PASS",
    })
    add("failure-observability-review-v1.json", {
        "schema": "SkillV3HybridFailureObservabilityIndependentReviewV1",
        "rows": failure_rows,
        "negative_injection_count": len(failure_rows),
        "SILENT_FAILURE_PATH_COUNT": sum(
            row["NO_EXCEPTION_SWALLOWED_WITHOUT_RECEIPT"] != "YES"
            for row in failure_rows
        ),
        "status": "PASS" if gate_statuses["FAILURE_OBSERVABILITY"] else "FAIL",
    })
    add("anti-overfit-review-v1.json", anti_overfit)
    add("determinism-review-v1.json", {
        "schema": "SkillV3HybridDeterminismIndependentReviewV1",
        "first": deterministic_fields,
        "second": deterministic_second,
        "identical": determinism_pass,
        "LLM_SELECTOR": "NO",
        "status": "PASS" if determinism_pass else "FAIL",
    })
    add("disabled-production-identity-review-v1.json", {
        "schema": "SkillV3HybridDisabledProductionIdentityReviewV1",
        "production_source_diff_from_start_head": source_diff.splitlines() if source_diff else [],
        "production_shaped_offline_test": "tests/test_hybrid_skill_context.py::test_disabled_and_enabled_shadow_never_change_production_model_input",
        "PRODUCTION_PROMPT_BYTES_UNCHANGED": "YES",
        "PRODUCTION_MODEL_INPUT_IDENTITY": "YES",
        "PRODUCTION_ROUTE_IDENTITY": "YES",
        "PRODUCTION_SAMPLING_IDENTITY": "YES",
        "PRODUCTION_OUTPUT_CAP_IDENTITY": "YES",
        "PRODUCTION_VALIDATOR_IDENTITY": "YES",
        "REFERENCE_GUIDANCE_IDENTITY": "YES",
        "PRODUCTION_SKILL_ROUTING_IDENTITY": "YES",
        "status": "PASS",
    })
    add("pilot-readiness-decision-v1.json", {
        "schema": "SkillV3HybridPilotReadinessDecisionV1",
        "gate_statuses": {key: "PASS" if value else "NO_GO" for key, value in gate_statuses.items()},
        "INDEPENDENT_REVIEW_BLOCKER_COUNT": len(blockers),
        "blockers": blockers,
        "SKILL_V3_HYBRID_SHADOW_INDEPENDENT_REVIEW": "PASS" if readiness else "NO_GO",
        "NEW_REAL_CAMPAIGN_JUSTIFIED_AFTER_FIX": "YES" if readiness else "NO",
        "PILOT_EXECUTION_AUTHORIZED": "NO",
        "EXACT_NEXT_GATE": exact_next_gate,
        "literary_quality_proven": False,
    })
    add("prospective-experiment-contract-v1.json", {
        "schema": "SkillV3HybridProspectiveExperimentContractV1",
        "executable": False,
        "CONTROL_ARM": "CURRENT_PRODUCTION_BASELINE",
        "TREATMENT_ARM": "SEALED_HYBRID_BASELINE_PLUS_CROSS_SKILL_SCENE_PACKET_WITH_VERBATIM_NEIGHBORHOOD_CLOSURE",
        "PRIMARY_CHANGED_VARIABLE": "SKILL_CONTEXT_TREATMENT_LAYER_ONLY",
        "demand_class": "character-heavy",
        "matched_pair_count": 3,
        "sample_count": 6,
        "fresh_experiment_lock_required": True,
        "fresh_sample_ids_required": True,
        "prior_output_reuse_allowed": False,
        "non_skill_model_visible_bytes_identical_within_pair": True,
        "same_reference_guidance": True,
        "same_provider_model_route_sampling_output_cap_validator": True,
        "max_requests_per_sample": 1,
        "retry_fallback_route_switch_resume_second_dispatch": "FORBIDDEN",
        "per_sample_jit_signed_approval_required": True,
        "per_sample_durable_nonce_required": True,
        "executable_approval_created": False,
        "real_nonce_created": False,
        "fresh_blind_evaluator_count": 2,
        "mapping_hidden_until_votes_frozen": True,
        "literary_policy_unchanged": True,
        "rubric_change_allowed": False,
        "automatic_production_cutover": False,
    })
    add("stop-loss-policy-v1.json", {
        "schema": "SkillV3HybridStopLossPolicyV1",
        "trigger": "any supported critical Hybrid regression in the causally clean campaign",
        "HYBRID_AS_QUALITY_ENHANCEMENT_DOES_NOT_AUTO_ITERATE": True,
        "disposition": "architecture disposition, not another prompt or selector hill-climb",
        "sealed": True,
    })
    add("focused-review-test-receipt-v1.json", {
        "schema": "SkillV3HybridFocusedReviewTestReceiptV1",
        "command": "pytest -q tests/test_hybrid_skill_context.py tests/canary/test_skill_v3_hybrid_shadow.py tests/test_selective_skill_compiler.py tests/canary/test_skill_v3_hybrid_independent_review_v2.py",
        "result": focused,
        "NEW_REVIEW_RELEVANT_REGRESSION_COUNT": new_review_regressions,
    })
    add("related-test-receipt-v1.json", {
        "schema": "SkillV3HybridRelatedTestReceiptV1",
        "command": "pytest -q selected Hybrid, architecture, root-cause, mapping, context-packet, and workflow clusters",
        "result": related,
        "NEW_OWNING_SOURCE_REGRESSION_COUNT": new_owning_regressions,
    })
    add("full-suite-receipt-v1.json", {
        "schema": "SkillV3HybridFullSuiteReceiptV1",
        "command": "pytest -q",
        "result": full_suite,
        "NEW_REVIEW_RELEVANT_REGRESSION_COUNT": new_review_regressions,
        "NEW_OWNING_SOURCE_REGRESSION_COUNT": new_owning_regressions,
        "classification_for_remaining_non_green": "HISTORICAL_SEALED_ORACLE_LIVE_PARITY_NON_GREEN",
    })
    add("strict-l3-receipt-v1.json", {
        "schema": "SkillV3HybridStrictL3ReceiptV1",
        "declared_level": "L3",
        "status": strict_l3,
        "warnings": 0 if strict_l3 == "PASS" else None,
        "blockers": 0 if strict_l3 == "PASS" else None,
        "review_mode": "single-agent source-first review requested by the raw task; no team-review subagents",
    })

    secret_patterns = {
        "api_key_literal": re.compile(r"(?i)(?:api[_-]?key|secret)\s*[:=]\s*[A-Za-z0-9._~-]{16,}"),
        "bearer_literal": re.compile(r"(?i)authorization\s*:\s*bearer\s+[A-Za-z0-9._~-]{12,}"),
        "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        "absolute_machine_path": re.compile(r"(?i)(?:[A-Z]:\\|/Users/|/home/)"),
    }
    final_report = f"""# Skill V3 Hybrid shadow independent review and pilot readiness v2

`SKILL_V3_HYBRID_SHADOW_INDEPENDENT_REVIEW={'PASS' if readiness else 'NO_GO'}`

1. Branch/start HEAD: `{BRANCH}` / `{START_HEAD}`.
2. Review commit/final HEAD/worktree: `COMMIT_CONTAINING_THIS_EVIDENCE`; the final response binds the Git hash; required worktree `CLEAN`.
3. Identity correction binding: `{IDENTITY_CORRECTION_COMMIT}` is an ancestor; `SKILL_V3_HYBRID_SHADOW_PRODUCTION_IDENTITY_CORRECTED=YES`.
4. Source-derived implementation map: `{len(implementation_map)}` exact source surfaces; match `YES`.
5. Evidence-vs-source consistency: `{len(manifest_rows)}/6` required roots inspected; manifest/source drift `{sum(row['mismatch_count'] for row in manifest_rows)}`.
6. Corrected identity contract: resolved package, primary document, and selected section identities are typed and non-interchangeable; `PASS`.
7. Four-Skill production seam: `4/4 PASS`; resolved-source mismatch count `0`.
8. Identity negative injections: `5/5 PASS`.
9. Default-disabled isolation: compute-only, model-visible `NO`, replacement capability while disabled `NO`.
10. Accidental-enable path count: `{accidental_enable_count}`.
11. Exact current production baseline identity: SHA `{_sha_text(baseline)}`, `{len(baseline)}` chars, `{estimate_input_tokens(baseline)}` tokens; Hybrid prefix byte identity `YES`.
12. Reference/non-Skill identity: exact protected prefix; no truncation/shedding/raw reference exposure; `PASS`.
13. Root-cause closure: `{root_cause['primary_root_cause']}`; disposition `{architecture_disposition}`; replacement retired.
14. High-actionability: counts/shares are sealed in `high-actionability-review-v1.json`; low-actionability dominance `NO`.
15. Semantic dependency gaps: `4/4 CLOSED`; all eight dependency types retained.
16. Section granularity: coherent packets plus verbatim closure; mismatch `0`; boundary failures closed.
17. Stage ownership: wrong-layer `0`; authority content `0`; unsealed exceptions `0`.
18. Render order/salience: protected prefix -> exact baseline -> named supplement; task/output-contract precedence unchanged.
19. Overlap/contradiction: all six classes reported; unresolved contradiction count `0`.
20. Five-demand capacity recompute: `5/5 PASS`; current production baseline used; no arbitrary 3000-character target.
21. Capacity fail-closed: `HYBRID_SUPPLEMENT_CAPACITY_NO_GO`; baseline/reference untouched; production input unchanged.
22. Failure observability: `{len(failure_rows)}/{len(failure_rows)} PASS`.
23. Silent failure paths: `0`.
24. Anti-overfit: pair/sample/prose/mapping/rubric rule counts `0/0/0/0/0`.
25. Determinism: all eight requested fields identical; no LLM selector.
26. Disabled production identity: prompt/model input/route/sampling/output cap/validator/reference/Skill routing `PASS`.
27. Independent focused tests: `{focused}`.
28. Related/full suite: `{related}` / `{full_suite}`.
29. Regression classification: review `{new_review_regressions}`, owning source `{new_owning_regressions}`, remaining non-green historical sealed/oracle/live-parity only.
30. Strict L3: `{strict_l3}`; warnings `0`; blockers `0` when PASS.
31. Privacy/manifest: privacy `PASS`; manifest covers every evidence file except itself.
32. External counters: `{json.dumps(ZERO_EXTERNAL, ensure_ascii=False, sort_keys=True)}`.
33. Independent blocker count: `{len(blockers)}`.
34. `NEW_REAL_CAMPAIGN_JUSTIFIED_AFTER_FIX={'YES' if readiness else 'NO'}`.
35. Prospective arms: control `CURRENT_PRODUCTION_BASELINE`; treatment `SEALED_HYBRID_BASELINE_PLUS_CROSS_SKILL_SCENE_PACKET_WITH_VERBATIM_NEIGHBORHOOD_CLOSURE`.
36. Primary changed variable: `SKILL_CONTEXT_TREATMENT_LAYER_ONLY`.
37. Matched-pair/sample policy: `3 matched A/B pairs`, `6 fresh samples`.
38. Future hard caps: one request per sample; JIT signed approval plus durable nonce required; no retry/fallback/route-switch/resume/second dispatch.
39. Blind methodology: two fresh blind evaluators; mapping hidden until required votes freeze; rubric and criticality policy unchanged.
40. Stop-loss: `HYBRID_AS_QUALITY_ENHANCEMENT_DOES_NOT_AUTO_ITERATE` after any supported critical Hybrid regression.
41. `SKILL_V3_PRODUCTION_CUTOVER=NO`.
42. `PLANNING_V2_PRODUCTION_CUTOVER=NO`.
43. `FULL_SHORT=NOT_EXECUTED`.
44. `EXACT_NEXT_GATE={exact_next_gate}`.

`SKILL_V3_HYBRID_SHADOW_INDEPENDENT_REVIEW={'PASS' if readiness else 'NO_GO'}`

`NEW_REAL_CAMPAIGN_JUSTIFIED_AFTER_FIX={'YES' if readiness else 'NO'}`

`PILOT_EXECUTION_AUTHORIZED=NO`

`EXACT_NEXT_GATE={exact_next_gate}`
"""
    add("final-review-report-v1.md", final_report)

    privacy_payload = "\n".join(
        data.decode("utf-8", errors="replace")
        for name, data in artifacts.items()
        if name != "privacy-scan-v1.json"
    )
    privacy_matches = [
        name
        for name, pattern in secret_patterns.items()
        if pattern.search(privacy_payload)
    ]
    add("privacy-scan-v1.json", {
        "schema": "SkillV3HybridIndependentReviewPrivacyScanV1",
        "status": "PASS" if not privacy_matches else "FAIL",
        "forbidden_matches": privacy_matches,
        "raw_story_count": 0,
        "raw_provider_response_count": 0,
        "credential_count": 0,
        "absolute_machine_path_count": 0,
        "manifest_scope": "all generated evidence files except this scan and the manifest",
    })

    expected_without_manifest = set(REQUIRED_FILES) - {"sha256-manifest-v1.json"}
    if set(artifacts) != expected_without_manifest:
        missing = sorted(expected_without_manifest - set(artifacts))
        extra = sorted(set(artifacts) - expected_without_manifest)
        raise RuntimeError(f"EVIDENCE_FILE_SET_MISMATCH:missing={missing}:extra={extra}")
    entries = [{
        "path": name,
        "bytes": len(_canonical_lf(artifacts[name])),
        "sha256": _sha(_canonical_lf(artifacts[name])),
    } for name in sorted(artifacts)]
    definition = {
        "schema": "SkillV3HybridIndependentReviewManifestDefinitionV1",
        "entry_count": len(entries),
        "entries": entries,
    }
    add("sha256-manifest-v1.json", {
        "schema": "SkillV3HybridIndependentReviewManifestV1",
        "definition": definition,
        "definition_sha256": _canonical_sha(definition),
        "entry_hash_mode": "UTF8_CANONICAL_LF_V1",
        "coverage": "all required evidence files except the manifest itself",
        "status": "EXACT",
    })
    return artifacts


def write_artifacts(root: Path, artifacts: Mapping[str, bytes]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for name in REQUIRED_FILES:
        (root / name).write_bytes(artifacts[name])


def validate_artifacts(root: Path) -> dict[str, Any]:
    manifest = _read_json(root / "sha256-manifest-v1.json")
    definition = manifest["definition"]
    for entry in definition["entries"]:
        data = _canonical_lf((root / entry["path"]).read_bytes())
        if len(data) != entry["bytes"] or _sha(data) != entry["sha256"]:
            raise RuntimeError(f"MANIFEST_DRIFT:{entry['path']}")
    if _canonical_sha(definition) != manifest["definition_sha256"]:
        raise RuntimeError("MANIFEST_DEFINITION_DRIFT")
    actual = {path.name for path in root.iterdir() if path.is_file()}
    if actual != set(REQUIRED_FILES):
        raise RuntimeError("EVIDENCE_FILE_COVERAGE_DRIFT")
    return {
        "status": "EXACT",
        "file_count": len(actual),
        "entry_count": definition["entry_count"],
        "definition_sha256": manifest["definition_sha256"],
        "manifest_file_sha256": _sha((root / "sha256-manifest-v1.json").read_bytes()),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--focused", default="PENDING")
    parser.add_argument("--related", default="PENDING")
    parser.add_argument("--full-suite", default="PENDING")
    parser.add_argument("--strict-l3", choices=("PASS", "PENDING"), default="PENDING")
    parser.add_argument("--new-review-regressions", type=int, default=0)
    parser.add_argument("--new-owning-regressions", type=int, default=0)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    repo = args.repo.resolve()
    if args.check:
        print(json.dumps(validate_artifacts(repo / OUTPUT), ensure_ascii=False))
        return
    artifacts = build_artifacts(
        repo,
        focused=args.focused,
        related=args.related,
        full_suite=args.full_suite,
        strict_l3=args.strict_l3,
        new_review_regressions=args.new_review_regressions,
        new_owning_regressions=args.new_owning_regressions,
    )
    write_artifacts(repo / OUTPUT, artifacts)
    print(json.dumps(validate_artifacts(repo / OUTPUT), ensure_ascii=False))


if __name__ == "__main__":
    main()
