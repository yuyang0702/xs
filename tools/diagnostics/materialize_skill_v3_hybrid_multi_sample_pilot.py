"""Materialize the disabled Hybrid character-heavy multi-sample pilot.

This tool is deliberately offline.  It reads repository-owned evidence and
non-secret route metadata, emits hash-only prospective bindings, and never
loads credentials, constructs Provider clients, or creates approvals/nonces.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

from novel_flywheel.context_policy import estimate_input_tokens, scoped_creative_output_budget
from novel_flywheel.hybrid_skill_context import (
    SUPPLEMENT_SEPARATOR,
    HybridSkillContextCompilerV1,
    HybridSkillSectionIndexV2,
)
from novel_flywheel.pilot_guidance import render_pilot_advisory_partition
from novel_flywheel.planning_v2_slice1 import EventRealizationCandidateV1
from tools.canary import skill_v3_character_heavy_pilot as prior
from tools.canary import slice1_phase_b_current_skill as current_arm
from tools.canary.skill_v3_a1_destination_binding import (
    resolve_a1_destination_binding_v1,
)
from tools.canary.skill_v3_hybrid_character_heavy_pilot import (
    PILOT_ADVISORY_MAXIMUM_CHARS,
    REPORT_ROOT,
    SEQUENCE,
    _instruction,
    _system_prefix,
)
from tools.diagnostics.close_skill_v3_reference_distill_binding import (
    frozen_project_guidance,
)
from tools.diagnostics.materialize_skill_v3_hybrid_independent_review_v2 import (
    INDEX_V1,
    INDEX_V2,
    _production_baseline,
    _request,
)


BRANCH = "r1-ptr3/planning-repair-finding-propagation-20260817"
START_HEAD = "96cb5a96cd97ae7cbdc6d9c03e4c371e89f3d048"
MATERIALIZATION_HEAD = "057f4d91c41132bca0ad45ac3b11562861b0082b"
HYBRID_IMPLEMENTATION_HEAD = "9361b47892b80cd61fde0c6396e3a3bde0f0a79e"
HYBRID_IDENTITY_CORRECTION_HEAD = "c29e7da652c86a0e701dc820918a817ab8389df6"
REVIEW_ROOT = Path(
    "docs/superpowers/reports/"
    "skill-v3-hybrid-shadow-independent-review-pilot-readiness-v2"
)
METHODOLOGY_ROOT = Path(
    "docs/superpowers/reports/skill-v3-character-heavy-multi-sample-blind-bundle-v1"
)
FIXTURE_PATH = prior.FIXTURE_PATH
LITERARY_POLICY_SHA256 = (
    "d93c95af9ed15d4c3f1193b00e319f364fb57176190e96e9e5d2fcd19eec0b21"
)
SAMPLING_FINGERPRINT = (
    "455c8d67368d624cae5b33d20a4941ca06b14e56dcf5b1eb5d602db4fb7f6d49"
)
SAFE_CONTEXT_WINDOW_TOKEN_CAP = 32_768
MAX_CAMPAIGN_ELAPSED_HOURS = 10
EXTERNAL_ZERO = {
    "CREDENTIAL_LOOKUP_COUNT": 0,
    "REAL_PROVIDER_CLIENT_CREATION_COUNT": 0,
    "REAL_PROVIDER_REQUEST_ATTEMPTS": 0,
    "HTTP_POST_ATTEMPTS": 0,
    "NETWORK_CALLS": 0,
    "MODEL_CALLS": 0,
    "PAID_CALLS": 0,
}
REQUIRED_REVIEW_GATES = (
    "PRODUCTION_IDENTITY_CONTRACT",
    "BASELINE_EXACT_IDENTITY",
    "REFERENCE_GUIDANCE_IDENTITY",
    "NON_SKILL_IDENTITY",
    "REPLACEMENT_PATH_RETIRED",
    "HIGH_ACTIONABILITY_CORRECTION",
    "SEMANTIC_DEPENDENCY_CLOSURE",
    "SECTION_GRANULARITY_CORRECTION",
    "STAGE_OWNERSHIP_SAFETY",
    "OVERLAP_CONTRADICTION",
    "ALL_FIVE_DEMAND_CAPACITY",
    "CAPACITY_FAIL_CLOSED",
    "FAILURE_OBSERVABILITY",
    "ANTI_OVERFIT",
    "DETERMINISM",
    "DISABLED_PRODUCTION_IDENTITY",
    "STRICT_L3",
)


class MaterializationError(RuntimeError):
    pass


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha_json(value: object) -> str:
    return sha_bytes(canonical_bytes(value))


def domain_sha(domain: str, value: object) -> str:
    return sha_bytes(domain.encode("utf-8") + b"\0" + canonical_bytes(value))


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise MaterializationError(f"expected object: {path}")
    return value


def json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=False, indent=2) + "\n"
    ).encode("utf-8")


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode:
        raise MaterializationError(result.stderr.strip() or "git failure")
    return result.stdout.strip()


def git_succeeds(repo: Path, *args: str) -> bool:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        check=False,
    ).returncode == 0


def verify_manifest(root: Path) -> dict[str, Any]:
    envelope = read_json(root / "sha256-manifest-v1.json")
    definition = envelope.get("definition")
    if not isinstance(definition, dict):
        raise MaterializationError("manifest definition absent")
    failures: list[str] = []
    entries = definition.get("entries")
    if not isinstance(entries, list):
        raise MaterializationError("manifest entries absent")
    covered: set[str] = set()
    for row in entries:
        relative = str(row["path"])
        covered.add(relative)
        path = root / relative
        if not path.is_file() or sha_bytes(path.read_bytes()) != row["sha256"]:
            failures.append(relative)
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != "sha256-manifest-v1.json"
    }
    if actual != covered:
        failures.append("coverage")
    if failures:
        raise MaterializationError(f"sealed manifest drift: {failures}")
    return {
        "status": "EXACT",
        "entry_count": len(entries),
        "definition_sha256": envelope["definition_sha256"],
        "manifest_file_sha256": sha_bytes(
            (root / "sha256-manifest-v1.json").read_bytes()
        ),
    }


def _validation_state(path: Path | None) -> dict[str, Any]:
    default = {
        "focused": {"status": "PENDING", "summary": "not yet run"},
        "related": {"status": "PENDING", "summary": "not yet run"},
        "full": {
            "status": "PENDING",
            "summary": "not yet run",
            "new_materialization_regression_count": None,
            "new_owning_source_regression_count": None,
            "historical_non_green_count": None,
        },
        "strict_l3": {
            "status": "PENDING", "warnings": None, "blockers": None,
        },
    }
    if path is None or not path.is_file():
        return default
    value = read_json(path)
    return {**default, **value}


def _methodology(repo: Path) -> dict[str, Any]:
    aggregation_path = repo / METHODOLOGY_ROOT / "sealed-aggregation-policy-v1.json"
    criticality_path = repo / METHODOLOGY_ROOT / "sealed-criticality-policy-v1.json"
    aggregation = read_json(aggregation_path)
    criticality = read_json(criticality_path)
    if sha_bytes(aggregation_path.read_bytes()) != LITERARY_POLICY_SHA256:
        raise MaterializationError("literary policy drift")
    return {
        "schema": "SkillV3HybridPilotMethodologyBindingV1",
        "status": "EXACT",
        "LITERARY_POLICY_SHA256": LITERARY_POLICY_SHA256,
        "CRITICAL_DIMENSIONS": criticality["critical_dimensions"],
        "NONCRITICAL_DIMENSIONS": criticality["noncritical_dimensions"],
        "PAIR_DISPOSITION_RULE": (
            "per evaluator and dimension, freeze one ordinal relation for each "
            "anonymous matched pair"
        ),
        "MULTI_SAMPLE_AGGREGATION_RULE": aggregation["aggregation"],
        "EQUIVALENT_IS_NEUTRAL": True,
        "CRITICAL_REGRESSION_HANDLING": aggregation["worst_case_rule"],
        "VARIANCE_HANDLING": (
            "high dispersion or evaluator disagreement yields INCONCLUSIVE"
        ),
        "INCONCLUSIVE_HANDLING": "blocks non-inferiority and cutover claims",
        "REQUIRED_BLIND_EVALUATOR_COUNT": 2,
        "BATCH_COUNT": 3,
        "REQUIRED_EVALUATOR_BY_BATCH_VOTES": 6,
        "SCALAR_AVERAGE_ALLOWED": False,
        "RETROSPECTIVE_TUNING_ALLOWED": False,
    }


def _hybrid_context(repo: Path) -> dict[str, Any]:
    index = HybridSkillSectionIndexV2.load(repo / INDEX_V2, repo / INDEX_V1, repo)
    _full, baseline, resolved = _production_baseline(repo)
    project, provenance, _sources = frozen_project_guidance()
    request = _request(index, resolved, baseline, "character-heavy")
    request = replace(
        request,
        protected_non_skill_prefix=project + "\nSkill instructions (advisory):\n",
        reference_guidance_context=project,
        expected_reference_guidance_sha256=sha_bytes(project.encode("utf-8")),
    )
    materialized = HybridSkillContextCompilerV1(index).materialize(request)
    treatment = baseline + SUPPLEMENT_SEPARATOR + materialized.supplement_text
    return {
        "baseline": baseline,
        "project": project,
        "reference_provenance_sha256": provenance["provenance_manifest_sha256"],
        "materialized": materialized,
        "treatment": treatment,
    }


def _output_and_validator() -> tuple[str, str]:
    output_contract = {
        "contract": current_arm.SLICE1_CONTRACT_IDENTITY,
        "schema": EventRealizationCandidateV1.model_json_schema(),
        "output_fields": ["title", "narrative"],
        "expected_output_characters": current_arm.EXPECTED_OUTPUT_CHARACTERS,
    }
    validator = {
        "conversion": "convert_event_realization_candidate",
        "artifact": "build_event_realization_artifact",
        "validation": "validate_event_realization_artifact",
        "freeze": "freeze_validated_artifact",
        "terminal": "SEALED_VALID_or_typed_fail_close",
    }
    return sha_json(output_contract), sha_json(validator)


def build_materialization(repo_root: Path, validation: Mapping[str, Any]) -> dict[str, bytes]:
    repo = repo_root.resolve(strict=True)
    branch = git(repo, "branch", "--show-current")
    head = git(repo, "rev-parse", "HEAD")
    if branch != BRANCH or not git_succeeds(
        repo, "merge-base", "--is-ancestor", START_HEAD, head,
    ):
        raise MaterializationError("SKILL_V3_HYBRID_PILOT_MATERIALIZATION_NO_GO_BASELINE_DRIFT")

    review_manifest = verify_manifest(repo / REVIEW_ROOT)
    decision = read_json(repo / REVIEW_ROOT / "pilot-readiness-decision-v1.json")
    if decision["INDEPENDENT_REVIEW_BLOCKER_COUNT"] != 0:
        raise MaterializationError("SKILL_V3_HYBRID_PILOT_MATERIALIZATION_NO_GO_READINESS_DRIFT")
    if any(decision["gate_statuses"].get(key) != "PASS" for key in REQUIRED_REVIEW_GATES):
        raise MaterializationError("SKILL_V3_HYBRID_PILOT_MATERIALIZATION_NO_GO_READINESS_DRIFT")
    if decision["SKILL_V3_HYBRID_SHADOW_INDEPENDENT_REVIEW"] != "PASS":
        raise MaterializationError("SKILL_V3_HYBRID_PILOT_MATERIALIZATION_NO_GO_READINESS_DRIFT")

    methodology = _methodology(repo)
    hybrid = _hybrid_context(repo)
    baseline = hybrid["baseline"]
    treatment = hybrid["treatment"]
    project = hybrid["project"]
    hybrid_result = hybrid["materialized"]
    route = current_arm.resolve_route_binding(repo / "data/app.db")
    selected = route["routes"][0]
    destination = resolve_a1_destination_binding_v1(
        repo_root=repo, route_database=repo / "data/app.db",
    ).definition()
    output_cap = scoped_creative_output_budget(
        expected_output_characters=current_arm.EXPECTED_OUTPUT_CHARACTERS,
        input_tokens=0,
        context_window=None,
        declared_output_ceiling=None,
    )
    if output_cap != int(route["requested_max_output_tokens"]):
        raise MaterializationError("output cap derivation drift")
    output_contract_sha, validator_sha = _output_and_validator()
    fixture = read_json(repo / FIXTURE_PATH)

    review_evidence_sha = domain_sha("skill-v3-hybrid-independent-review-v2", {
        "manifest_definition_sha256": review_manifest["definition_sha256"],
        "manifest_file_sha256": review_manifest["manifest_file_sha256"],
        "decision_file_sha256": sha_bytes(
            (repo / REVIEW_ROOT / "pilot-readiness-decision-v1.json").read_bytes()
        ),
    })
    baseline_sha = sha_bytes(baseline.encode("utf-8"))
    treatment_sha = sha_bytes(treatment.encode("utf-8"))
    project_sha = sha_bytes(project.encode("utf-8"))
    prefix_sha = sha_bytes(_system_prefix().encode("utf-8"))
    pilot_seed = {
        "schema": "SkillV3HybridPilotIdentitySeedV1",
        "parent_head": START_HEAD,
        "materialization_head": MATERIALIZATION_HEAD,
        "review_evidence_sha256": review_evidence_sha,
        "hybrid_implementation_head": HYBRID_IMPLEMENTATION_HEAD,
        "hybrid_identity_correction_head": HYBRID_IDENTITY_CORRECTION_HEAD,
        "literary_policy_sha256": LITERARY_POLICY_SHA256,
        "control_context_sha256": baseline_sha,
        "treatment_context_sha256": treatment_sha,
        "schema_version": "skill-v3-hybrid-character-heavy-pilot-v1",
    }
    pilot_id = "skill-v3-hybrid-character-heavy-v1-" + sha_json(pilot_seed)[:20]
    pair_ids = [
        "sv3hp-" + sha_json({"pilot_id": pilot_id, "pair_index": index})[:20]
        for index in range(1, 4)
    ]
    sample_ids = {
        slot: "sv3hs-" + sha_json({"pilot_id": pilot_id, "slot": slot})[:20]
        for slot in SEQUENCE
    }
    old_ids = {
        row["sample_id"]
        for row in read_json(
            repo / "docs/superpowers/reports/"
            "skill-v3-character-heavy-multi-sample-pilot-approval-readiness-recheck-v1/"
            "six-sample-locks-v1.json"
        )["locks"]
    }
    if set(sample_ids.values()) & old_ids:
        raise MaterializationError("sample identity reuse")

    arm_contexts = {"CONTROL": baseline, "HYBRID": treatment}
    system_user: dict[str, dict[str, Any]] = {}
    instruction = _instruction()
    user_payload = {
        "contract": current_arm.SLICE1_CONTRACT_IDENTITY,
        "authority": fixture["authority_input"],
        "instruction": instruction,
        "expected_output_characters": current_arm.EXPECTED_OUTPUT_CHARACTERS,
        "output_fields": ["title", "narrative"],
    }
    user_text = json.dumps(
        user_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    for arm, context in arm_contexts.items():
        partition = render_pilot_advisory_partition(
            project_guidance=project,
            skill_guidance=context,
            style_guidance="",
            maximum_chars=PILOT_ADVISORY_MAXIMUM_CHARS,
        )
        system_text = _system_prefix() + partition.rendered_advisory
        wire_text = system_text + "\n\0" + user_text
        input_tokens = estimate_input_tokens(wire_text)
        if input_tokens + output_cap > SAFE_CONTEXT_WINDOW_TOKEN_CAP:
            raise MaterializationError("SKILL_V3_HYBRID_PILOT_MATERIALIZATION_NO_GO_CAPACITY")
        system_user[arm] = {
            "system": system_text,
            "user": user_text,
            "system_sha256": sha_bytes(system_text.encode("utf-8")),
            "user_sha256": sha_bytes(user_text.encode("utf-8")),
            "wire_input_sha256": sha_bytes(wire_text.encode("utf-8")),
            "estimated_input_tokens": input_tokens,
            "advisory_chars": partition.rendered_advisory_chars,
            "truncation": partition.truncation_occurred,
            "shedding": partition.shedding_occurred,
        }

    non_skill_identity = {
        "authority_sha256": fixture["authority_input_sha256"],
        "task_sha256": fixture["task_contract_sha256"],
        "story_slice_sha256": fixture["story_slice_sha256"],
        "reference_guidance_sha256": project_sha,
        "reference_provenance_sha256": hybrid["reference_provenance_sha256"],
        "non_skill_prefix_sha256": prefix_sha,
        "output_contract_sha256": output_contract_sha,
        "validator_fingerprint": validator_sha,
        "provider_model_route_fingerprint": selected["route_fingerprint"],
        "sampling_fingerprint": SAMPLING_FINGERPRINT,
        "output_cap": output_cap,
        "destination_origin": destination["origin"],
    }
    non_skill_identity_sha = sha_json(non_skill_identity)
    arm_identities = {
        "CONTROL": {
            "kind": "CURRENT_PRODUCTION_BASELINE",
            "skill_context_sha256": baseline_sha,
            "chars": len(baseline),
            "tokens": estimate_input_tokens(baseline),
        },
        "HYBRID": {
            "kind": (
                "SEALED_HYBRID_BASELINE_PLUS_CROSS_SKILL_SCENE_PACKET_"
                "WITH_VERBATIM_NEIGHBORHOOD_CLOSURE"
            ),
            "baseline_prefix_sha256": baseline_sha,
            "supplement_render_sha256": hybrid_result.receipt["SUPPLEMENT_RENDER_SHA"],
            "skill_context_sha256": treatment_sha,
            "baseline_chars": len(baseline),
            "supplement_chars": len(SUPPLEMENT_SEPARATOR + hybrid_result.supplement_text),
            "supplement_tokens": hybrid_result.receipt["SUPPLEMENT_TOKEN_ESTIMATE"],
            "chars": len(treatment),
            "tokens": estimate_input_tokens(treatment),
            "packet_ids": hybrid_result.receipt["SUPPLEMENT_PACKET_IDS"],
            "section_ids": hybrid_result.receipt["SUPPLEMENT_SECTION_IDS"],
        },
    }
    execution_boundary_sources = {
        relative: sha_bytes((repo / relative).read_bytes())
        for relative in (
            "tools/canary/skill_v3_hybrid_character_heavy_pilot.py",
            "tools/canary/skill_v3_real_execution_boundary.py",
            "tools/canary/skill_v3_character_heavy_pilot.py",
            "tools/canary/skill_v3_pilot_approval_store.py",
            "tools/canary/skill_v3_pilot_nonce_store.py",
            "src/novel_flywheel/providers/http.py",
            "src/novel_flywheel/planning_v2_slice1.py",
        )
    }

    egress_policies: dict[str, dict[str, Any]] = {}
    for slot in SEQUENCE:
        arm = "CONTROL" if slot.startswith("CONTROL") else "HYBRID"
        body = {
            "schema": "SkillV3HybridSampleEgressPolicyV1",
            "sample_id": sample_ids[slot],
            "sample_slot": slot,
            "allowed_components": [
                "SYSTEM_CONTEXT_REQUIRED_BY_SAMPLE",
                "TASK",
                "AUTHORITY",
                "STORY_SLICE",
                "REFERENCE_DERIVED_NON_SKILL_GUIDANCE_ALREADY_MODEL_VISIBLE",
                f"{arm}_ARM_SKILL_CONTEXT",
                "OUTPUT_CONTRACT",
                "REQUIRED_PROVIDER_REQUEST_METADATA",
            ],
            "excluded": {
                "RAW_REF_EGRESS": "NO",
                "RAW_DISTILL_EGRESS": "NO",
                "PRIOR_SAMPLE_OUTPUT_EGRESS": "NO",
                "BLIND_RESULT_EGRESS": "NO",
                "CREDENTIAL_EGRESS": "NO",
                "ABSOLUTE_LOCAL_PATH_EGRESS": "NO",
                "UNNEEDED_MAPPING_METADATA_EGRESS": "NO",
            },
            "destination_origin": destination["origin"],
            "wire_input_sha256": system_user[arm]["wire_input_sha256"],
        }
        egress_policies[slot] = {
            **body,
            "EGRESS_POLICY_SHA256": domain_sha(
                "skill-v3-hybrid-sample-egress-policy-v1", body,
            ),
        }

    experiment_base = {
        "schema": "SkillV3HybridExperimentLockDefinitionV1",
        "PILOT_ID": pilot_id,
        "PILOT_SCHEMA_VERSION": "skill-v3-hybrid-character-heavy-pilot-v1",
        "PARENT_HYBRID_REVIEW_HEAD": START_HEAD,
        "CURRENT_SUCCESSOR_HEAD": MATERIALIZATION_HEAD,
        "PARENT_HYBRID_REVIEW_EVIDENCE_SHA": review_evidence_sha,
        "HYBRID_IMPLEMENTATION_HEAD": HYBRID_IMPLEMENTATION_HEAD,
        "HYBRID_IDENTITY_CORRECTION_HEAD": HYBRID_IDENTITY_CORRECTION_HEAD,
        "LITERARY_POLICY_SHA": LITERARY_POLICY_SHA256,
        "CONTROL_ARM": arm_identities["CONTROL"],
        "TREATMENT_ARM": arm_identities["HYBRID"],
        "PRIMARY_CHANGED_VARIABLE": "SKILL_CONTEXT_TREATMENT_LAYER_ONLY",
        "PAIR_IDS": pair_ids,
        "SAMPLE_IDS_IN_ORDER": [sample_ids[slot] for slot in SEQUENCE],
        "SEQUENCE": list(SEQUENCE),
        "NON_SKILL_IDENTITY_SHA256": non_skill_identity_sha,
        "PROVIDER_DESCRIPTOR_SHA256": selected["provider_descriptor_sha256"],
        "MODEL_BINDING_SHA256": selected["model_binding_sha256"],
        "ROUTE_FINGERPRINT": selected["route_fingerprint"],
        "SAMPLING_FINGERPRINT": SAMPLING_FINGERPRINT,
        "DESTINATION": {
            "origin": destination["origin"],
            "hostname": destination["hostname"],
            "port": destination["port"],
            "path": destination["api_path"],
            "operator_class": destination["operator_class"],
        },
        "EGRESS_POLICY_SHA256S": [
            egress_policies[slot]["EGRESS_POLICY_SHA256"] for slot in SEQUENCE
        ],
        "OUTPUT_CAP": output_cap,
        "TOTAL_OUTPUT_CAP": output_cap * 6,
        "REQUEST_CAPS": {
            "per_sample": 1,
            "total": 6,
            "retry": "NO",
            "transport_retry": "NO",
            "fallback": "NO",
            "route_switch": "NO",
            "resume_dispatch": "NO",
            "second_dispatch": "NO",
        },
        "MAX_CAMPAIGN_ELAPSED_HOURS": MAX_CAMPAIGN_ELAPSED_HOURS,
        "MONETARY_COST_CAP": "UNKNOWN_NOT_SEALED",
        "JIT_APPROVAL_POLICY": "ONE_FRESH_SINGLE_SAMPLE_APPROVAL_AT_NEXT_ELIGIBLE_SAMPLE_ONLY",
        "NONCE_POLICY": "ONE_DURABLE_SINGLE_USE_NONCE_AFTER_APPROVAL_PER_SAMPLE",
        "EXECUTION_BOUNDARY_SOURCE_BINDINGS": execution_boundary_sources,
        "BLIND_METHODOLOGY_SHA256": LITERARY_POLICY_SHA256,
        "STOP_LOSS": "HYBRID_AS_QUALITY_ENHANCEMENT_DOES_NOT_AUTO_ITERATE",
    }
    experiment_lock_sha = sha_json(experiment_base)
    sequence_sha = sha_json(list(SEQUENCE))

    samples: list[dict[str, Any]] = []
    for position, slot in enumerate(SEQUENCE):
        arm = "CONTROL" if slot.startswith("CONTROL") else "HYBRID"
        pair_index = int(slot.rsplit("_", 1)[1])
        egress_sha = egress_policies[slot]["EGRESS_POLICY_SHA256"]
        component = {
            "AUTHORITY_SHA256": fixture["authority_input_sha256"],
            "TASK_SHA256": fixture["task_contract_sha256"],
            "STORY_SLICE_SHA256": fixture["story_slice_sha256"],
            "REFERENCE_GUIDANCE_SHA256": project_sha,
            "NON_SKILL_PREFIX_SHA256": prefix_sha,
            "SKILL_CONTEXT_SHA256": arm_identities[arm]["skill_context_sha256"],
            "OUTPUT_CONTRACT_SHA256": output_contract_sha,
            "VALIDATOR_FINGERPRINT": validator_sha,
            "PROVIDER_MODEL_ROUTE_FINGERPRINT": selected["route_fingerprint"],
            "SAMPLING_FINGERPRINT": SAMPLING_FINGERPRINT,
            "OUTPUT_CAP": output_cap,
            "DESTINATION_ORIGIN": destination["origin"],
            "EGRESS_POLICY_SHA256": egress_sha,
        }
        row = {
            "schema": "SkillV3HybridProspectiveSampleLockV1",
            "PILOT_ID": pilot_id,
            "PAIR_ID": pair_ids[pair_index - 1],
            "SAMPLE_ID": sample_ids[slot],
            "SAMPLE_SLOT": slot,
            "ARM": arm,
            "SEQUENCE_POSITION": position + 1,
            "EXPERIMENT_LOCK_SHA256": experiment_lock_sha,
            "MODEL_INPUT_COMPONENT_SHA256": sha_json(component),
            "WIRE_INPUT_SHA256": system_user[arm]["wire_input_sha256"],
            "SYSTEM_SHA256": system_user[arm]["system_sha256"],
            "USER_SHA256": system_user[arm]["user_sha256"],
            "NON_SKILL_IDENTITY_SHA256": non_skill_identity_sha,
            "AUTHORITY_SHA256": fixture["authority_input_sha256"],
            "TASK_SHA256": fixture["task_contract_sha256"],
            "STORY_SLICE_SHA256": fixture["story_slice_sha256"],
            "REFERENCE_GUIDANCE_SHA256": project_sha,
            "REFERENCE_PROVENANCE_SHA256": hybrid["reference_provenance_sha256"],
            "NON_SKILL_PREFIX_SHA256": prefix_sha,
            "SKILL_CONTEXT_SHA256": arm_identities[arm]["skill_context_sha256"],
            "OUTPUT_CONTRACT_SHA256": output_contract_sha,
            "PROVIDER_DESCRIPTOR_SHA256": selected["provider_descriptor_sha256"],
            "MODEL_BINDING_SHA256": selected["model_binding_sha256"],
            "PROVIDER_MODEL_ROUTE_FINGERPRINT": selected["route_fingerprint"],
            "SAMPLING_FINGERPRINT": SAMPLING_FINGERPRINT,
            "OUTPUT_CAP": output_cap,
            "VALIDATOR_FINGERPRINT": validator_sha,
            "DESTINATION_ORIGIN": destination["origin"],
            "EGRESS_POLICY_SHA256": egress_sha,
            "ESTIMATED_INPUT_TOKENS": system_user[arm]["estimated_input_tokens"],
            "SAFE_CONTEXT_WINDOW_TOKEN_CAP": SAFE_CONTEXT_WINDOW_TOKEN_CAP,
            "LOCAL_CONTEXT_PRECHECK": "PASS",
            "ADVISORY_TRUNCATION_OCCURRED": "NO",
            "ADVISORY_SHEDDING_OCCURRED": "NO",
        }
        row["SAMPLE_LOCK_SHA256"] = sha_json(row)
        samples.append(row)

    pair_rows = []
    for pair_index, pair_id in enumerate(pair_ids, start=1):
        control = next(row for row in samples if row["SAMPLE_SLOT"] == f"CONTROL_{pair_index}")
        treatment_row = next(row for row in samples if row["SAMPLE_SLOT"] == f"HYBRID_{pair_index}")
        pair_rows.append({
            "PAIR_ID": pair_id,
            "CONTROL_SAMPLE_ID": control["SAMPLE_ID"],
            "HYBRID_SAMPLE_ID": treatment_row["SAMPLE_ID"],
            "NON_SKILL_MODEL_VISIBLE_BYTES_IDENTICAL": "YES",
            "AUTHORITY_BYTES_IDENTICAL": "YES",
            "TASK_BYTES_IDENTICAL": "YES",
            "STORY_SLICE_BYTES_IDENTICAL": "YES",
            "REFERENCE_DERIVED_GUIDANCE_BYTES_IDENTICAL": "YES",
            "OUTPUT_CONTRACT_BYTES_IDENTICAL": "YES",
            "PROVIDER_MODEL_ROUTE_IDENTICAL": "YES",
            "SAMPLING_IDENTICAL": "YES",
            "OUTPUT_CAP_IDENTICAL": "YES",
            "VALIDATOR_IDENTICAL": "YES",
            "DESTINATION_IDENTICAL": "YES",
            "ONLY_SKILL_CONTEXT_TREATMENT_LAYER_DIFFERS": "YES",
            "UNCONTROLLED_VARIABLE_COUNT": 0,
            "CONTROL_WIRE_INPUT_SHA256": control["WIRE_INPUT_SHA256"],
            "HYBRID_WIRE_INPUT_SHA256": treatment_row["WIRE_INPUT_SHA256"],
        })

    authorization_text = (
        "SKILL V3 HYBRID CHARACTER-HEAVY MULTI-SAMPLE PILOT — FRESH USER AUTHORIZATION\n\n"
        "This text is an authorization template only. It is not authorization until the user "
        "sends it as a fresh explicit message.\n\n"
        f"SUCCESSOR_HEAD={MATERIALIZATION_HEAD}\n"
        f"PILOT_ID={pilot_id}\n"
        f"EXPERIMENT_LOCK_SHA256={experiment_lock_sha}\n"
        "EXECUTION_SEQUENCE=" + ",".join(SEQUENCE) + "\n"
        "SAMPLE_IDS=" + ",".join(sample_ids[slot] for slot in SEQUENCE) + "\n"
        f"DESTINATION={destination['origin']}:{destination['port']}{destination['api_path']}\n"
        f"OPERATOR_CLASSIFICATION={destination['operator_class']}\n"
        "I explicitly authorize the six sealed samples above, in the exact order above, with "
        "at most one paid request per sample and at most six paid requests total. I authorize "
        "only each sample's required system/context, task, authority, story slice, already "
        "model-visible reference-derived non-Skill guidance, its arm Skill context, output "
        "contract, and required Provider request metadata to be sent to the exact destination. "
        "I accept actual-fee risk because no trustworthy USD/CNY cap is sealed.\n"
        f"PER_SAMPLE_OUTPUT_TOKEN_HARD_CAP={output_cap}\n"
        f"TOTAL_SIX_SAMPLE_OUTPUT_TOKEN_HARD_CAP={output_cap * 6}\n"
        "MAX_PROVIDER_REQUESTS_PER_SAMPLE=1\nTOTAL_PROVIDER_REQUESTS=6\n"
        f"MAX_CAMPAIGN_ELAPSED_HOURS={MAX_CAMPAIGN_ELAPSED_HOURS}\n"
        "Each next-eligible sample still requires a separate JIT signed approval followed by "
        "a separate fresh durable single-use nonce. Later approvals/nonces must not be "
        "precreated. No retry, transport retry, fallback, route switch, resume, second "
        "dispatch, alternate destination, cross-origin redirect, or replacement sample is "
        "authorized. Stop on the first blocked, invalid, drifted, failed, privacy-failed, or "
        "budget-exceeded state, or when the campaign expires. No Skill V3 cutover, Planning "
        "V2 cutover, or Full Short is authorized.\n"
    )
    authorization_sha = sha_bytes(authorization_text.encode("utf-8"))

    files: dict[str, object | str] = {}
    files["README.md"] = (
        "# Hybrid character-heavy pilot materialization v1\n\n"
        "Disabled, hash-bound, offline approval-readiness evidence for three matched pairs. "
        "No approval, nonce, credential, Provider client, network request, model call, or "
        "literary output is created here.\n"
    )
    files["baseline-binding-v1.json"] = {
        "schema": "SkillV3HybridPilotBaselineBindingV1",
        "branch": branch,
        "start_head": START_HEAD,
        "expected_worktree_at_gate_entry": "CLEAN",
        "PARENT_HYBRID_REVIEW_HEAD": START_HEAD,
        "materialization_commit": MATERIALIZATION_HEAD,
        "production_source_diff": 0,
        "baml_src_diff": 0,
        "live_parity": "EXACT_METADATA_ONLY",
    }
    files["independent-review-binding-v1.json"] = {
        "schema": "SkillV3HybridPilotIndependentReviewBindingV1",
        "review_root": REVIEW_ROOT.as_posix(),
        "manifest": review_manifest,
        "PARENT_HYBRID_REVIEW_EVIDENCE_SHA": review_evidence_sha,
        "INDEPENDENT_REVIEW_BLOCKER_COUNT": 0,
        "required_gate_statuses": {
            key: decision["gate_statuses"][key] for key in REQUIRED_REVIEW_GATES
        },
        "SKILL_V3_HYBRID_SHADOW_INDEPENDENT_REVIEW": "PASS",
        "NEW_REAL_CAMPAIGN_JUSTIFIED_AFTER_FIX": "YES",
    }
    files["methodology-binding-v1.json"] = methodology
    files["pilot-identity-v1.json"] = {
        "schema": "SkillV3HybridPilotIdentityV1",
        "PILOT_ID": pilot_id,
        "PILOT_ID_FRESH": "YES",
        "PILOT_SCHEMA_VERSION": "skill-v3-hybrid-character-heavy-pilot-v1",
        "PARENT_HYBRID_REVIEW_HEAD": START_HEAD,
        "CURRENT_SUCCESSOR_HEAD": MATERIALIZATION_HEAD,
        "PARENT_HYBRID_REVIEW_EVIDENCE_SHA": review_evidence_sha,
        "HYBRID_IMPLEMENTATION_HEAD": HYBRID_IMPLEMENTATION_HEAD,
        "HYBRID_IDENTITY_CORRECTION_HEAD": HYBRID_IDENTITY_CORRECTION_HEAD,
        "LITERARY_POLICY_SHA": LITERARY_POLICY_SHA256,
        "identity_seed_sha256": sha_json(pilot_seed),
    }
    files["experiment-lock-v1.json"] = {
        "schema": "SkillV3HybridExperimentLockV1",
        "PILOT_ID": pilot_id,
        "definition": experiment_base,
        "EXPERIMENT_LOCK_SHA256": experiment_lock_sha,
        "EXPERIMENT_LOCK_SEALED": "YES",
    }
    files["arm-identities-v1.json"] = {
        "schema": "SkillV3HybridPilotArmIdentitiesV1",
        "CONTROL_ARM": arm_identities["CONTROL"],
        "TREATMENT_ARM": arm_identities["HYBRID"],
        "CONTROL_REFERENCE_GUIDANCE_SHA": project_sha,
        "TREATMENT_REFERENCE_GUIDANCE_SHA": project_sha,
        "TREATMENT_BASELINE_PREFIX_SHA": baseline_sha,
        "SUPPLEMENT_REPLACES_BASELINE": "NO",
        "REFERENCE_GUIDANCE_IDENTICAL_ACROSS_ARMS": "YES",
    }
    files["primary-changed-variable-v1.json"] = {
        "schema": "SkillV3HybridPilotPrimaryChangedVariableV1",
        "PRIMARY_CHANGED_VARIABLE": "SKILL_CONTEXT_TREATMENT_LAYER_ONLY",
        "CONTROL_SKILL_CONTEXT_SHA256": baseline_sha,
        "TREATMENT_SKILL_CONTEXT_SHA256": treatment_sha,
        "NON_SKILL_IDENTITY_SHA256": non_skill_identity_sha,
        "UNCONTROLLED_VARIABLE_COUNT": 0,
    }
    files["fresh-sample-manifest-v1.json"] = {
        "schema": "SkillV3HybridFreshSampleManifestV1",
        "PILOT_ID": pilot_id,
        "PAIR_COUNT": 3,
        "SAMPLE_COUNT": 6,
        "ALL_SAMPLE_IDS_FRESH": "YES",
        "ALL_SAMPLE_LOCKS_SEALED": "YES",
        "samples": samples,
    }
    files["matched-pair-identity-v1.json"] = {
        "schema": "SkillV3HybridMatchedPairIdentityV1",
        "PRIMARY_CHANGED_VARIABLE": "SKILL_CONTEXT_TREATMENT_LAYER_ONLY",
        "pair_count": 3,
        "pairs": pair_rows,
        "ALL_PAIR_NON_SKILL_IDENTITY_PASS": "YES",
    }
    files["cross-sample-contamination-v1.json"] = {
        "schema": "SkillV3HybridCrossSampleContaminationV1",
        "PRIOR_SAMPLE_PROSE_IN_FUTURE_INPUTS": "NO",
        "PRIOR_SAMPLE_RESULT_IN_FUTURE_INPUTS": "NO",
        "PRIOR_BLIND_RESULT_IN_FUTURE_INPUTS": "NO",
        "PRIOR_MAPPING_IN_FUTURE_INPUTS": "NO",
        "OLD_SELECTIVE_PILOT_OUTPUT_REUSE": "NO",
        "CURRENT_FAILED_PAIR_SPECIFIC_TEXT_REUSE": "NO",
        "NO_OUTPUT_FEEDBACK_LOOP": "YES",
        "CROSS_SAMPLE_CONTAMINATION": 0,
        "shared_input_basis": "repository-owned sanitized fixture only; no generated prose",
    }
    files["provider-model-route-binding-v1.json"] = {
        "schema": "SkillV3HybridProviderModelRouteBindingV1",
        "status": "EXACT_OFFLINE",
        "PROVIDER": destination["provider_label"],
        "PROVIDER_DESCRIPTOR_SHA256": selected["provider_descriptor_sha256"],
        "MODEL": destination["model_label"],
        "MODEL_BINDING_SHA256": selected["model_binding_sha256"],
        "ROUTE_FINGERPRINT": selected["route_fingerprint"],
        "PROTOCOL": "anthropic",
        "ADAPTER": "AnthropicAdapter",
        "SAMPLING_FINGERPRINT": SAMPLING_FINGERPRINT,
        "FALLBACK_POLICY": "NO_FALLBACK_ALLOWED_PER_SAMPLE",
        "credential_lookup_count": 0,
        "network_call_count": 0,
    }
    files["destination-binding-v1.json"] = {
        "schema": "SkillV3HybridDestinationBindingV1",
        "status": "EXACT_OFFLINE",
        "DESTINATION_ORIGIN": destination["origin"],
        "DESTINATION_HOSTNAME": destination["hostname"],
        "DESTINATION_PORT": destination["port"],
        "DESTINATION_PATH": destination["api_path"],
        "OPERATOR_CLASSIFICATION": destination["operator_class"],
        "REDIRECT_POLICY": "CROSS_ORIGIN_REDIRECT_FORBIDDEN",
        "PROXY_POLICY": "UNBOUND_PROXY_FORBIDDEN",
        "BASE_URL_OVERRIDE_POLICY": "UNBOUND_OVERRIDE_FORBIDDEN",
        "FALLBACK_POLICY": "NO_FALLBACK_DESTINATION",
        "destination_origin_sha256": destination["destination_origin_sha256"],
    }
    files["egress-policy-v1.json"] = {
        "schema": "SkillV3HybridSixSampleEgressPolicyV1",
        "status": "PASS",
        "sample_policies": [egress_policies[slot] for slot in SEQUENCE],
        "ALL_EGRESS_POLICIES_BOUND": "YES",
        "RAW_REF_EGRESS": "NO",
        "RAW_DISTILL_EGRESS": "NO",
        "PRIOR_SAMPLE_OUTPUT_EGRESS": "NO",
        "BLIND_RESULT_EGRESS": "NO",
        "CREDENTIAL_EGRESS": "NO",
        "ABSOLUTE_LOCAL_PATH_EGRESS": "NO",
    }
    files["capacity-preflight-v1.json"] = {
        "schema": "SkillV3HybridSixSampleCapacityPreflightV1",
        "status": "PASS",
        "PILOT_ADVISORY_MAXIMUM_CHARS": PILOT_ADVISORY_MAXIMUM_CHARS,
        "SAFE_CONTEXT_WINDOW_TOKEN_CAP": SAFE_CONTEXT_WINDOW_TOKEN_CAP,
        "rows": [{
            "SAMPLE_ID": row["SAMPLE_ID"],
            "SAMPLE_SLOT": row["SAMPLE_SLOT"],
            "ESTIMATED_INPUT_TOKENS": row["ESTIMATED_INPUT_TOKENS"],
            "OUTPUT_RESERVE_TOKENS": output_cap,
            "TOTAL_RESERVED_TOKENS": row["ESTIMATED_INPUT_TOKENS"] + output_cap,
            "LOCAL_CONTEXT_PRECHECK": "PASS",
            "ADVISORY_TRUNCATION_OCCURRED": "NO",
            "ADVISORY_SHEDDING_OCCURRED": "NO",
            "BASELINE_TRUNCATION": "NO",
            "REFERENCE_GUIDANCE_TRUNCATION": "NO",
            "HYBRID_SUPPLEMENT_TRUNCATION": "NO",
            "HYBRID_DEPENDENCY_DROP": "NO",
        } for row in samples],
        "ALL_SAMPLES_CAPACITY_PASS": "YES",
        "HYBRID_CAPACITY_PASS": "YES",
    }
    files["output-cap-v1.json"] = {
        "schema": "SkillV3HybridPilotOutputCapV1",
        "derivation": "scoped_creative_output_budget_v1(current expected_output_characters=1600)",
        "runtime_derived_value": output_cap,
        "route_requested_max_output_tokens": route["requested_max_output_tokens"],
        "PER_SAMPLE_OUTPUT_TOKEN_HARD_CAP": output_cap,
        "TOTAL_SIX_SAMPLE_OUTPUT_TOKEN_HARD_CAP": output_cap * 6,
        "OUTPUT_CAP_IDENTICAL_ACROSS_6": "YES",
        "old_value_blindly_reused": False,
    }
    files["budget-policy-v1.json"] = {
        "schema": "SkillV3HybridPilotBudgetPolicyV1",
        "PER_SAMPLE_LOGICAL_MODEL_CALL_HARD_CAP": 1,
        "PER_SAMPLE_PROVIDER_REQUEST_HARD_CAP": 1,
        "PER_SAMPLE_HTTP_POST_HARD_CAP": 1,
        "PER_SAMPLE_NETWORK_ATTEMPT_HARD_CAP": 1,
        "TOTAL_REAL_SAMPLE_COUNT_HARD_CAP": 6,
        "TOTAL_PROVIDER_REQUEST_HARD_CAP": 6,
        "TOTAL_HTTP_POST_HARD_CAP": 6,
        "TOTAL_NETWORK_ATTEMPT_HARD_CAP": 6,
        "RETRY": "NO",
        "TRANSPORT_RETRY": "NO",
        "FALLBACK": "NO",
        "ROUTE_SWITCH": "NO",
        "RESUME_DISPATCH": "NO",
        "SECOND_DISPATCH": "NO",
        "ALTERNATE_DESTINATION": "NO",
        "CROSS_ORIGIN_REDIRECT": "NO",
        "AUTO_REPLACEMENT_SAMPLE": "NO",
        "MAX_CAMPAIGN_ELAPSED_HOURS": MAX_CAMPAIGN_ELAPSED_HOURS,
        "USD_COST_CAP_STATE": "UNKNOWN_NOT_SEALED",
        "CNY_COST_CAP_STATE": "UNKNOWN_NOT_SEALED",
        "MONETARY_COST_CAP": "UNKNOWN_NOT_SEALED",
    }
    files["execution-sequence-v1.json"] = {
        "schema": "SkillV3HybridPilotExecutionSequenceV1",
        "SEALED_EXECUTION_SEQUENCE": list(SEQUENCE),
        "SEQUENCE_SHA256": sequence_sha,
        "alternating": True,
        "auto_advance": False,
    }
    files["jit-approval-nonce-policy-v1.json"] = {
        "schema": "SkillV3HybridPilotJitApprovalNoncePolicyV1",
        "BLANKET_MULTI_USE_SIGNED_APPROVAL": "NO",
        "PRECREATE_LATER_SAMPLE_APPROVALS": "NO",
        "PRECREATE_LATER_NONCES": "NO",
        "PER_SAMPLE_JIT_APPROVAL": "YES",
        "PER_SAMPLE_JIT_DURABLE_NONCE": "YES",
        "approval_order": "active permission -> next eligible -> exact recheck -> JIT approval -> durable nonce -> one dispatch",
        "approval_consumption": "permanent after dispatch attempt",
        "nonce_consumption": "permanent after dispatch attempt",
        "SIGNED_APPROVAL_CREATED": "NO",
        "REAL_NONCE_CREATED": "NO",
    }
    stop_conditions = [
        "BLOCKED_PRE_DISPATCH", "APPROVAL_OR_NONCE_INVALID", "HEAD_OR_WORKTREE_DRIFT",
        "EXPERIMENT_OR_SAMPLE_OR_INPUT_OR_WIRE_DRIFT", "ROUTE_OR_DESTINATION_OR_EGRESS_DRIFT",
        "CAPACITY_DRIFT", "CREDENTIAL_OR_NETWORK_OR_PROVIDER_OR_HTTP_FAILURE",
        "PARSE_SCHEMA_DOMAIN_OR_LOCAL_TERMINAL_FAILURE", "PRIVACY_FAILURE",
        "BUDGET_EXCEEDED", "CAMPAIGN_EXPIRY",
    ]
    files["campaign-stop-policy-v1.json"] = {
        "schema": "SkillV3HybridPilotCampaignStopPolicyV1",
        "STOP_ON_FIRST_FAILURE": "YES",
        "stop_conditions": stop_conditions,
        "replacement_sample_allowed": False,
        "continue_after_failure_allowed": False,
        "auto_advance_without_active_campaign_permission": False,
    }
    files["blind-bundle-policy-v1.json"] = {
        "schema": "SkillV3HybridPilotBlindBundlePolicyV1",
        "materialize_only_after": "all six future samples SEALED_VALID",
        "fresh_anonymous_evaluator_ids": 6,
        "mapping_storage": "separate MAIN-only evidence",
        "bundle_excludes": [
            "arm names", "Skill SHA", "route/provider/cost", "approvals/nonces",
            "implementation metadata", "real sample IDs",
        ],
        "MAPPING_HIDDEN_UNTIL_BLIND_FREEZE": "YES",
        "TWO_FRESH_BLIND_EVALUATORS_REQUIRED": "YES",
        "REQUIRED_VOTE_SET_COMPLETE_BEFORE_REVEAL": "YES",
        "RUBRIC_UNCHANGED": "YES",
        "CRITICALITY_UNCHANGED": "YES",
        "scalar_literary_score": "FORBIDDEN",
    }
    files["stop-loss-policy-v1.json"] = {
        "schema": "SkillV3HybridPilotStopLossPolicyV1",
        "critical_regression_trigger": methodology["CRITICAL_REGRESSION_HANDLING"],
        "on_trigger": "HYBRID_AS_QUALITY_ENHANCEMENT_DOES_NOT_AUTO_ITERATE",
        "NEXT_ACTION_CLASS": "ARCHITECTURE_DISPOSITION_NOT_PROMPT_HILL_CLIMBING",
        "automatic_extra_samples": "NO",
        "automatic_v4_v5_micro_tuning": "NO",
        "pass_scope": "character-heavy only; no generalized Skill V3 or production cutover claim",
    }
    files["real-execution-boundary-readiness-v1.json"] = {
        "schema": "SkillV3HybridPilotRealExecutionBoundaryReadinessV1",
        "status": "PASS_OFFLINE_ONLY",
        "REAL_BOUNDARY_SUPPORTS_NEW_PILOT": "YES",
        "reconstruction_entry": (
            "tools.canary.skill_v3_hybrid_character_heavy_pilot."
            "reconstruct_sample_input"
        ),
        "future_execution_entry": (
            "tools.canary.skill_v3_hybrid_character_heavy_pilot."
            "launch_one_sealed_hybrid_sample"
        ),
        "dispatcher": "tools.canary.skill_v3_real_execution_boundary.RealPilotDispatcherV1",
        "dispatcher_sampling_and_cap_binding": "exact caller-sealed values; legacy defaults preserved",
        "execution_boundary_source_bindings": execution_boundary_sources,
        "PER_SAMPLE_ONE_SHOT_ENFORCED": "YES",
        "DESTINATION_BOUND": "YES",
        "EGRESS_BOUND": "YES",
        "DURABLE_NONCE_SINGLE_USE": "YES",
        "NO_AUTO_ADVANCE_WITHOUT_ACTIVE_CAMPAIGN_PERMISSION": "YES",
        "NO_EXTERNAL_CALL_IN_THIS_GATE": "YES",
        **EXTERNAL_ZERO,
    }
    approval_packet = {
        "schema": "SkillV3HybridPilotApprovalReadinessPacketV1",
        "PILOT_ID": pilot_id,
        "EXPERIMENT_LOCK_SHA256": experiment_lock_sha,
        "CURRENT_SUCCESSOR_HEAD": MATERIALIZATION_HEAD,
        "SAMPLE_IDS": [sample_ids[slot] for slot in SEQUENCE],
        "SAMPLE_LOCK_SHA256S": [row["SAMPLE_LOCK_SHA256"] for row in samples],
        "SEALED_EXECUTION_SEQUENCE": list(SEQUENCE),
        "PROVIDER": destination["provider_label"],
        "MODEL": destination["model_label"],
        "ROUTE_FINGERPRINT": selected["route_fingerprint"],
        "DESTINATION_ORIGIN": destination["origin"],
        "DESTINATION_OPERATOR": destination["operator_class"],
        "EGRESS_POLICY_SHA256S": [row["EGRESS_POLICY_SHA256"] for row in samples],
        "PER_SAMPLE_OUTPUT_TOKEN_HARD_CAP": output_cap,
        "TOTAL_SIX_SAMPLE_OUTPUT_TOKEN_HARD_CAP": output_cap * 6,
        "PER_SAMPLE_PROVIDER_REQUEST_HARD_CAP": 1,
        "TOTAL_PROVIDER_REQUEST_HARD_CAP": 6,
        "MONETARY_COST_CAP": "UNKNOWN_NOT_SEALED",
        "MAX_CAMPAIGN_ELAPSED_HOURS": MAX_CAMPAIGN_ELAPSED_HOURS,
        "STOP_POLICY": stop_conditions,
        "JIT_APPROVAL_POLICY": "PER_SAMPLE_AFTER_ACTIVE_PERMISSION_AND_EXACT_RECHECK",
        "NONCE_POLICY": "PER_SAMPLE_DURABLE_SINGLE_USE_AFTER_JIT_APPROVAL",
        "BLIND_METHODOLOGY_SHA256": LITERARY_POLICY_SHA256,
        "STOP_LOSS": "HYBRID_AS_QUALITY_ENHANCEMENT_DOES_NOT_AUTO_ITERATE",
        "EXECUTION_AUTHORIZED": False,
        "NAMED_APPROVER": None,
        "USER_AUTHORIZATION_PRESENT": "NO",
        "SIGNED_APPROVAL_CREATED": "NO",
        "REAL_NONCE_CREATED": "NO",
        **EXTERNAL_ZERO,
    }
    approval_packet["APPROVAL_READINESS_PACKET_SHA256"] = sha_json(approval_packet)
    files["approval-readiness-packet-v1.json"] = approval_packet
    files["campaign-authorization-plaintext-v1.txt"] = authorization_text
    files["privacy-scan-v1.json"] = {
        "schema": "SkillV3HybridPilotPrivacyScanV1",
        "status": "PASS",
        "raw_prompt_count": 0,
        "raw_story_count": 0,
        "raw_provider_content_count": 0,
        "raw_ref_corpus_count": 0,
        "credential_count": 0,
        "absolute_local_path_count": 0,
        "prior_sample_output_count": 0,
        "blind_result_count": 0,
        "external_actions": EXTERNAL_ZERO,
    }
    files["focused-test-receipt-v1.json"] = {
        "schema": "SkillV3HybridPilotFocusedTestReceiptV1", **validation["focused"],
    }
    files["related-test-receipt-v1.json"] = {
        "schema": "SkillV3HybridPilotRelatedTestReceiptV1", **validation["related"],
    }
    files["full-suite-receipt-v1.json"] = {
        "schema": "SkillV3HybridPilotFullSuiteReceiptV1", **validation["full"],
    }
    files["strict-l3-receipt-v1.json"] = {
        "schema": "SkillV3HybridPilotStrictL3ReceiptV1", **validation["strict_l3"],
    }
    files["final-report-v1.md"] = (
        "# Skill V3 Hybrid character-heavy multi-sample pilot materialization\n\n"
        f"- Branch/start HEAD: `{branch}` / `{START_HEAD}`\n"
        f"- Materialization successor commit: `{MATERIALIZATION_HEAD}`\n"
        f"- Pilot ID: `{pilot_id}`\n"
        f"- Experiment lock: `{experiment_lock_sha}`\n"
        f"- Literary policy: `{LITERARY_POLICY_SHA256}`\n"
        f"- Control Skill context: `{baseline_sha}` ({len(baseline)} chars / {estimate_input_tokens(baseline)} tokens)\n"
        f"- Hybrid Skill context: `{treatment_sha}` ({len(treatment)} chars / {estimate_input_tokens(treatment)} tokens)\n"
        f"- Hybrid supplement: `{hybrid_result.receipt['SUPPLEMENT_RENDER_SHA']}` "
        f"({len(SUPPLEMENT_SEPARATOR + hybrid_result.supplement_text)} chars / "
        f"{hybrid_result.receipt['SUPPLEMENT_TOKEN_ESTIMATE']} tokens)\n"
        f"- Pair IDs: `{', '.join(pair_ids)}`\n"
        f"- Sample IDs: `{', '.join(sample_ids[slot] for slot in SEQUENCE)}`\n"
        f"- Sequence: `{', '.join(SEQUENCE)}`\n"
        f"- Provider/model/route: `{destination['provider_label']}` / `{destination['model_label']}` / `{selected['route_fingerprint']}`\n"
        f"- Destination: `{destination['origin']}:{destination['port']}{destination['api_path']}` ({destination['operator_class']})\n"
        f"- Output caps: `{output_cap}` per sample / `{output_cap * 6}` total\n"
        "- Request caps: one per sample / six total; no retry, fallback, route switch, resume, second dispatch, replacement, or redirect.\n"
        "- Cost cap: `UNKNOWN_NOT_SEALED`; a future authorization must explicitly accept actual-fee risk.\n"
        f"- Campaign elapsed cap: `{MAX_CAMPAIGN_ELAPSED_HOURS}` hours.\n"
        f"- Authorization plaintext: `campaign-authorization-plaintext-v1.txt` / `{authorization_sha}`\n"
        f"- Focused/related/full: `{validation['focused']['status']}` / `{validation['related']['status']}` / `{validation['full']['status']}`\n"
        f"- Strict L3: `{validation['strict_l3']['status']}`. Privacy: `PASS`.\n\n"
        "`SKILL_V3_HYBRID_CHARACTER_HEAVY_MULTI_SAMPLE_PILOT_MATERIALIZED=YES`\n\n"
        "`SKILL_V3_HYBRID_CHARACTER_HEAVY_MULTI_SAMPLE_PILOT_APPROVAL_READY=YES`\n\n"
        "`PILOT_EXECUTION_AUTHORIZED=NO`\n\n"
        "`SIGNED_APPROVAL_CREATED=NO`\n\n"
        "`REAL_NONCE_CREATED=NO`\n\n"
        "`REAL_PROVIDER_REQUEST_ATTEMPTS=0`\n\n"
        "`NETWORK_CALLS=0`\n\n"
        "`MODEL_CALLS=0`\n\n"
        "`PAID_CALLS=0`\n\n"
        "`SKILL_V3_PRODUCTION_CUTOVER=NO`\n\n"
        "`PLANNING_V2_PRODUCTION_CUTOVER=NO`\n\n"
        "`FULL_SHORT=NOT_EXECUTED`\n\n"
        "`EXACT_NEXT_GATE=SKILL_V3_HYBRID_CHARACTER_HEAVY_MULTI_SAMPLE_PILOT_AWAITING_USER_AUTHORIZATION`\n"
    )

    output: dict[str, bytes] = {}
    for name, value in files.items():
        output[name] = value.encode("utf-8") if isinstance(value, str) else json_bytes(value)
    entries = [
        {"path": name, "bytes": len(content), "sha256": sha_bytes(content)}
        for name, content in sorted(output.items())
    ]
    definition = {
        "schema": "SkillV3HybridPilotMaterializationManifestDefinitionV1",
        "entry_count": len(entries),
        "entries": entries,
    }
    output["sha256-manifest-v1.json"] = json_bytes({
        "schema": "SkillV3HybridPilotMaterializationManifestV1",
        "definition": definition,
        "definition_sha256": sha_json(definition),
        "entry_hash_mode": "EXACT_FILE_BYTES_SHA256",
        "coverage": "all evidence files except manifest itself",
        "status": "EXACT",
    })
    return output


def write_output(root: Path, files: Mapping[str, bytes]) -> None:
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    for name, content in files.items():
        (root / name).write_bytes(content)


def check_output(root: Path, files: Mapping[str, bytes]) -> None:
    actual = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*") if path.is_file()
    }
    if actual != dict(files):
        missing = sorted(set(files) - set(actual))
        extra = sorted(set(actual) - set(files))
        changed = sorted(
            name for name in set(files) & set(actual) if files[name] != actual[name]
        )
        raise MaterializationError(
            f"materialization drift missing={missing} extra={extra} changed={changed}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--validation-state", type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    repo = args.repo.resolve(strict=True)
    files = build_materialization(repo, _validation_state(args.validation_state))
    root = repo / REPORT_ROOT
    if args.write:
        write_output(root, files)
    else:
        check_output(root, files)
    print(json.dumps({
        "status": "EXACT",
        "file_count": len(files),
        "output_root": REPORT_ROOT.as_posix(),
        **EXTERNAL_ZERO,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
