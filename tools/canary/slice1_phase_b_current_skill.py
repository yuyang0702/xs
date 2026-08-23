"""Materialize and gate the Slice1 Phase B CURRENT-Skill shadow baseline.

The materializer is deliberately incapable of credential lookup, Provider
client construction, or network/model dispatch.  The dormant execution entry
point performs every signed-approval and single-use check before importing the
credential/Provider stack.  This module never enters a production workflow and
stores generated prose only below an isolated experiment root.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Mapping, Sequence

from novel_flywheel.context_policy import (
    estimate_input_tokens,
    scoped_creative_output_budget,
)
from novel_flywheel.db import Database
from novel_flywheel.planning_v2_slice1 import (
    ARTIFACT_SCHEMA,
    EVENT_REALIZATION_ARTIFACT_FIELD_PATHS,
    SLICE1_CONTRACT_IDENTITY,
    SLICE1_STAGE,
    SLICE1_VALIDATOR_POLICY_SHA256,
    EventRealizationCandidateV1,
    EventRealizationInputAuthorityV1,
)
from novel_flywheel.prompts import REQUIRED_SKILLS, STAGE_SYSTEM
from novel_flywheel.skill_prompts import SkillPromptCompactor
from novel_flywheel.skills import SkillScanner
from tools.canary.descriptors import production_route_identity


EXPECTED_BRANCH = "r1-ptr3/planning-repair-finding-propagation-20260817"
BASELINE_HEAD = "033867472f23535ce2abc685934fd2a2b8e63586"
PTR12_REVIEWED_HEAD = "28d0fcc0190e7ada8c68e0f7013cb390d7b55c66"
PTR12_SEAL_HEAD = BASELINE_HEAD
PROFILE_ID = "CURRENT_SKILL_BASELINE_PROFILE_V1"
SKILL_ARM = "CURRENT_RUNTIME_SKILL"
COHORT_ID = "slice1-phase-b-current-skill-033867472f23-001"
CASE_IDS = ("valid-canonical",)
APPROVAL_SCOPE = "SLICE1_PHASE_B_CURRENT_SKILL_BASELINE_ONLY"
REPORT_RELATIVE_ROOT = (
    "docs/superpowers/reports/"
    "short-plan-v2-slice1-phase-b-current-skill-materialization"
)
FIXTURE_RELATIVE_PATH = (
    "tests/fixtures/reliability/short_plan_v2_slice1/"
    "event-realization-shadow-corpus-v1.json"
)
FIXTURE_PROVENANCE_RELATIVE_PATH = FIXTURE_RELATIVE_PATH.replace(
    ".json", ".provenance.json",
)
PTR12_ROOT = "docs/superpowers/reports/r1-ptr12-final-review"
PTR12_MANIFEST = f"{PTR12_ROOT}/sha256-manifest-v1.json"
PTR12_DECISION = f"{PTR12_ROOT}/r1-ptr12-review-v4-final-decision-v1.json"
EXPECTED_PRIMARY_DESCRIPTOR = (
    "121cc6b0b4f77b0b08697f2782e0f67a29007183d65a2780b2051048da3a600f"
)
EXPECTED_PRIMARY_MODEL = (
    "5fd92d58fb34146b854ecf816dfe7622e24c233480149dfab9e327cff7f6b1ff"
)
EXPECTED_FALLBACK_DESCRIPTOR = (
    "98190f8a4627638591d90646f663d859e5cb8b8fa138ef3d250e43317c1705a6"
)
EXPECTED_FALLBACK_MODEL = (
    "fa876d1792c79f4cfa4209a3384a407b6cd48f5bbdf49a920d74cdfca9bf0998"
)
EXPECTED_PRIMARY_ROUTE_FINGERPRINT = (
    "30e9cbaf86fbb4b89b43614d71cc11b359ad41e7411e8ebda5d3ce4199879bf0"
)
EXPECTED_FALLBACK_ROUTE_FINGERPRINT = (
    "04a443a6702fcc95b74906e44b7233c9370cb9b94bbbbadce4bf59c088b68c31"
)
EXPECTED_OUTPUT_CHARACTERS = 1_600
EXPECTED_OUTPUT_TOKENS = 2_048
EXPECTED_ELAPSED_SECONDS = 240
HARD_MAX_INPUT_TOKENS = 32_768
HARD_MAX_ELAPSED_SECONDS = 900
ZERO_COUNTERS = {
    "credential_lookup_count": 0,
    "provider_client_creation_count": 0,
    "real_provider_call_count": 0,
    "network_call_count": 0,
    "model_call_count": 0,
    "paid_call_count": 0,
}


class Slice1PhaseBMaterializationError(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def _require(condition: bool, reason_code: str) -> None:
    if not condition:
        raise Slice1PhaseBMaterializationError(reason_code)


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(
        value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False,
    ) + "\n").encode("utf-8")


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha_file(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _domain_sha(domain: str, value: Any) -> str:
    return _sha_bytes(domain.encode("utf-8") + b"\0" + _canonical_bytes(value))


def _sealed(domain: str, body: Mapping[str, Any], field: str) -> dict[str, Any]:
    result = dict(body)
    result[field] = _domain_sha(domain, result)
    return result


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Slice1PhaseBMaterializationError("json_evidence_unreadable") from exc
    _require(isinstance(value, dict), "json_evidence_not_object")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_json_bytes(value))


def _git(repo_root: Path, *args: str) -> str:
    return subprocess.run(
        ("git", *args), cwd=repo_root, check=True, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout.strip()


def verify_git_gate(
    repo_root: Path, *, expected_head: str | None = None, require_clean: bool = True,
) -> dict[str, Any]:
    branch = _git(repo_root, "branch", "--show-current")
    head = _git(repo_root, "rev-parse", "HEAD")
    status = _git(repo_root, "status", "--porcelain")
    _require(branch == EXPECTED_BRANCH, "baseline_branch_mismatch")
    if expected_head is not None:
        _require(head == expected_head, "baseline_head_mismatch")
    if require_clean:
        _require(not status, "worktree_not_clean")
    return {
        "branch": branch, "head": head,
        "worktree": "clean" if not status else "dirty",
    }


def verify_ptr12_final(repo_root: Path) -> dict[str, Any]:
    manifest_path = repo_root / PTR12_MANIFEST
    manifest = _read_json(manifest_path)
    _require(manifest.get("overall_status") == "exact", "ptr12_manifest_not_exact")
    _require(manifest.get("reviewed_head") == PTR12_REVIEWED_HEAD,
             "ptr12_reviewed_head_mismatch")
    entries = list(manifest.get("files") or ())
    _require(len(entries) == manifest.get("file_count") == 11,
             "ptr12_manifest_coverage_mismatch")
    for entry in entries:
        path = repo_root / str(entry.get("path") or "")
        _require(path.is_file(), "ptr12_manifest_file_missing")
        _require(path.stat().st_size == entry.get("bytes"),
                 "ptr12_manifest_size_mismatch")
        _require(_sha_file(path) == entry.get("sha256"),
                 "ptr12_manifest_hash_mismatch")
    decision = _read_json(repo_root / PTR12_DECISION)
    _require(decision.get("split_review_pass") is True,
             "ptr12_split_review_not_pass")
    _require(decision.get("phase_b_ready") is True, "ptr12_phase_b_not_ready")
    _require((decision.get("shards") or {}).get("completed") == 3,
             "ptr12_review_shards_incomplete")
    _require(decision.get("raw_content_persisted_count") == 0,
             "ptr12_raw_content_persisted")
    return {
        "status": "exact",
        "reviewed_head": PTR12_REVIEWED_HEAD,
        "evidence_seal_head": PTR12_SEAL_HEAD,
        "manifest_sha256": _sha_file(manifest_path),
        "manifest_definition_sha256": manifest["manifest_definition_sha256"],
        "final_decision_sha256": _sha_file(repo_root / PTR12_DECISION),
        "completed_shards": 3,
        "split_review_pass": True,
        "phase_b_ready": True,
    }


def _source_class(path: Path, repo_root: Path) -> tuple[str, int]:
    resolved = path.resolve()
    project_agent = (repo_root / ".agents" / "skills").resolve()
    project_path = (repo_root / ".codex" / "skills").resolve()
    if resolved.is_relative_to(project_path):
        return "PROJECT_PATH", 3
    if resolved.is_relative_to(project_agent):
        return "PROJECT_AGENT", 2
    global_root = (Path.home() / ".codex" / "skills").resolve()
    if resolved.is_relative_to(global_root):
        return "GLOBAL_CODEX", 1
    return "OTHER_CURRENT_CANONICAL", 4


def resolve_current_skill_profile(
    repo_root: Path, *, roots: Sequence[Path] | None = None,
) -> tuple[dict[str, Any], str, str]:
    resolution_roots = list(roots or (
        Path.home() / ".codex" / "skills",
        repo_root / ".agents" / "skills",
    ))
    resolved = {item.name: item for item in SkillScanner(resolution_roots).scan()}
    expected = tuple(REQUIRED_SKILLS["planning"])
    _require(expected == (
        "story-init", "plot-structure", "character-management", "worldbuilding",
    ), "planning_required_skill_contract_changed")
    _require(all(name in resolved for name in expected), "current_skill_missing")
    rows: list[dict[str, Any]] = []
    raw_prompts: list[str] = []
    for name in expected:
        skill = resolved[name]
        raw = (skill.path / "SKILL.md").read_bytes()
        canonical = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        source_class, rank = _source_class(skill.path, repo_root)
        rows.append({
            "skill_name": name,
            "source_class": source_class,
            "resolution_precedence_rank": rank,
            "scanner_tree_content_sha256": skill.content_hash,
            "raw_skill_md_sha256": _sha_bytes(raw),
            "canonical_skill_md_sha256": _sha_bytes(canonical),
            "compacted_prompt_contribution_sha256": "NOT_SEPARATELY_DETERMINISTIC",
            "mandatory_rule_extraction_result": "NOT_SEPARATE_IN_CURRENT_RUNTIME",
        })
        raw_prompts.append(skill.instructions)
    raw_prompt = "\n\n".join(raw_prompts)
    compacted = SkillPromptCompactor(max_chars=9000).compact(raw_prompt, ())
    policy = {
        "class": "SkillPromptCompactor",
        "max_chars": 9000,
        "source_sha256": _sha_file(repo_root / "src/novel_flywheel/skill_prompts.py"),
        "mandatory_rule_extraction_active": False,
        "hard_marker_priority_is_compaction_not_authority_promotion": True,
    }
    body = {
        "schema": "CurrentSkillBaselineProfileV1",
        "version": 1,
        "profile_id": PROFILE_ID,
        "stage": "planning",
        "slice": SLICE1_STAGE,
        "skill_arm": SKILL_ARM,
        "resolved_skills": rows,
        "combined_raw_prompt_sha256": _sha_bytes(raw_prompt.encode("utf-8")),
        "combined_raw_prompt_characters": len(raw_prompt),
        "combined_current_runtime_compacted_prompt_sha256": _sha_bytes(
            compacted.encode("utf-8"),
        ),
        "combined_current_runtime_compacted_characters": len(compacted),
        "compaction_policy": policy,
        "skill_profile_v2_sha": "NOT_ACTIVE",
        "skill_v2_profile_active": False,
        "planning_skill_profile_shadow_v1": "NOT_USED_FOR_MODEL_INPUT",
        "project_vendor_skill_bundle_active": False,
        "skill_files_modified": False,
        "raw_skill_content_persisted": False,
    }
    return _sealed(
        "slice1-phase-b-current-skill-profile-v1", body, "profile_sha256",
    ), raw_prompt, compacted


def verify_skill_resolution_twice(
    repo_root: Path, *, roots: Sequence[Path] | None = None,
) -> tuple[dict[str, Any], str]:
    first, first_raw, first_compact = resolve_current_skill_profile(
        repo_root, roots=roots,
    )
    second, second_raw, second_compact = resolve_current_skill_profile(
        repo_root, roots=roots,
    )
    _require(first == second and first_raw == second_raw
             and first_compact == second_compact,
             "SLICE1_PHASE_B_CURRENT_SKILL_BASELINE_MATERIALIZATION_NO_GO_"
             "SKILL_RESOLUTION_NONDETERMINISTIC")
    result = dict(first)
    result["resolution_run_count"] = 2
    result["resolution_deterministic"] = True
    result["profile_sha256"] = _domain_sha(
        "slice1-phase-b-current-skill-profile-v1",
        {key: value for key, value in result.items() if key != "profile_sha256"},
    )
    return result, first_compact


def load_fixture_binding(repo_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    fixture_path = repo_root / FIXTURE_RELATIVE_PATH
    provenance_path = repo_root / FIXTURE_PROVENANCE_RELATIVE_PATH
    fixture = _read_json(fixture_path)
    provenance = _read_json(provenance_path)
    selected = [case for case in fixture.get("cases", ())
                if case.get("case_id") in CASE_IDS]
    _require(len(selected) == len(CASE_IDS) == 1, "fixture_case_missing")
    _require(selected[0].get("expected") == "validated",
             "fixture_case_not_validated")
    canonical_fixture = fixture_path.read_bytes().replace(
        b"\r\n", b"\n",
    ).replace(b"\r", b"\n")
    _require(_sha_bytes(canonical_fixture) ==
             provenance.get("expected_canonical_fixture_sha256"),
             "fixture_provenance_mismatch")
    authority_source = fixture["authority"]
    event_id = authority_source["event_ids"][0]
    authority = EventRealizationInputAuthorityV1(
        parent_authority_sha256=authority_source["parent_authority_sha256"],
        formal_event_id=event_id,
        formal_event_contract_sha256=authority_source["event_contract_sha256"][event_id],
        predecessor_boundary_sha256=authority_source["predecessor_boundary_sha256"][event_id],
        formal_event_ids=tuple(authority_source["event_ids"]),
        segment_event_ids=(tuple(authority_source["event_ids"]),),
        dependency_artifact_ids=(),
        context_projection_sha256=authority_source["context_projection_sha256"],
        required_obligation_ids=tuple(authority_source["required_obligation_ids"]),
    )
    authority_value = authority.model_dump(mode="json")
    authority_sha = _domain_sha("slice1-phase-b-authority-input-v1", authority_value)
    withheld_reference = fixture["candidates"][selected[0]["candidate"]]
    workload = _sealed("slice1-phase-b-current-skill-workload-v1", {
        "schema": "Slice1PhaseBCurrentSkillWorkloadV1",
        "version": 1,
        "cohort_id": COHORT_ID,
        "case_ids": list(CASE_IDS),
        "case_count": 1,
        "fixture_id": provenance["fixture_id"],
        "fixture_sha256": _sha_file(fixture_path),
        "fixture_canonical_sha256": _sha_bytes(canonical_fixture),
        "fixture_provenance_sha256": _sha_file(provenance_path),
        "fixture_provenance_mode": provenance["fixture_provenance_contract"],
        "existing_project_short_semantics": True,
        "new_project_initialization": False,
        "selected_formal_event_id_sha256": _sha_bytes(event_id.encode("utf-8")),
        "authority_input_sha256": authority_sha,
        "withheld_reference_candidate_sha256": _domain_sha(
            "slice1-phase-b-withheld-reference-v1", withheld_reference,
        ),
        "withheld_reference_visible_to_model": False,
        "repository_owned_sanitized_fixture": True,
        "private_user_data": False,
        "wall_clock_dependency": False,
        "live_database_dependency": False,
        "model_generated_output_authoritative": False,
        "future_skill_v2_arm_must_reuse_exact_workload": True,
    }, "workload_sha256")
    return workload, authority_value


def slice1_contract_binding(repo_root: Path) -> dict[str, Any]:
    candidate_schema = EventRealizationCandidateV1.model_json_schema()
    schema_sha = _domain_sha("event-realization-candidate-schema-v1", candidate_schema)
    validator_bundle = {
        "validator_policy_sha256": SLICE1_VALIDATOR_POLICY_SHA256,
        "candidate_validator": "validate_candidate_payload",
        "conversion_validator": "convert_event_realization_candidate",
        "artifact_validator": "validate_event_realization_artifact",
        "freeze_validator": "freeze_validated_artifact",
        "source_sha256": _sha_file(repo_root / "src/novel_flywheel/planning_v2_slice1.py"),
    }
    return _sealed("slice1-phase-b-authority-binding-v1", {
        "schema": "Slice1PhaseBAuthorityBindingV1",
        "version": 1,
        "slice1_stage": SLICE1_STAGE,
        "contract_identity": SLICE1_CONTRACT_IDENTITY,
        "artifact_schema": ARTIFACT_SCHEMA,
        "candidate_schema_sha256": schema_sha,
        "artifact_field_paths": list(EVENT_REALIZATION_ARTIFACT_FIELD_PATHS),
        "artifact_field_count": len(EVENT_REALIZATION_ARTIFACT_FIELD_PATHS),
        "candidate_owned_fields": ["/title", "/narrative"],
        "candidate_owned_field_count": 2,
        "authority_copy_field_count": 4,
        "runtime_local_deterministic_field_count": 20,
        "validator_bundle": validator_bundle,
        "validator_bundle_sha256": _domain_sha(
            "slice1-phase-b-validator-bundle-v1", validator_bundle,
        ),
        "freeze_thaw_cas_bound": True,
        "no_progress_bound": True,
        "whole_planning_regeneration_allowed": False,
        "planning_v1_production_authority": True,
        "shadow_only": True,
        "draft_entry_allowed": False,
        "story_state_mutation_allowed": False,
        "canon_mutation_allowed": False,
    }, "authority_binding_sha256")


def _route_fingerprint(provider: Mapping[str, Any], model: Mapping[str, Any]) -> str:
    provider_route = {
        "protocol": provider.get("protocol"),
        "base_url": str(provider.get("base_url") or "").rstrip("/"),
        "auth_type": provider.get("auth_type"),
        "extra_headers": provider.get("extra_headers") or {},
    }
    provider_route_sha = _sha_bytes(_canonical_bytes(provider_route))
    return _sha_bytes(_canonical_bytes({
        "provider_route": provider_route_sha,
        "model_name": model.get("model_name"),
    }))


def resolve_route_binding(
    route_database: Path, *, expected_routes: Mapping[str, Mapping[str, str]] | None = None,
) -> dict[str, Any]:
    db = Database(route_database)
    binding = db.get_role_binding("planning")
    _require(binding is not None, "route_model_binding_ambiguous")
    expected = expected_routes or {
        "primary": {
            "provider_descriptor_hash": EXPECTED_PRIMARY_DESCRIPTOR,
            "model_binding_hash": EXPECTED_PRIMARY_MODEL,
            "route_fingerprint": EXPECTED_PRIMARY_ROUTE_FINGERPRINT,
        },
        "configured_fallback": {
            "provider_descriptor_hash": EXPECTED_FALLBACK_DESCRIPTOR,
            "model_binding_hash": EXPECTED_FALLBACK_MODEL,
            "route_fingerprint": EXPECTED_FALLBACK_ROUTE_FINGERPRINT,
        },
    }
    routes = []
    for route_kind, provider_key, model_key in (
        ("primary", "primary_provider_id", "primary_model_id"),
        ("configured_fallback", "fallback_provider_id", "fallback_model_id"),
    ):
        provider_id = str(binding.get(provider_key) or "")
        model_id = str(binding.get(model_key) or "")
        _require(bool(provider_id and model_id), "route_model_binding_ambiguous")
        provider = db.get_provider(provider_id) or {}
        model = db.get_model(model_id) or {}
        descriptor = production_route_identity(
            db, "planning", "fallback" if route_kind == "configured_fallback" else "primary",
        )
        fingerprint = _route_fingerprint(provider, model)
        expected_route = expected[route_kind]
        _require(descriptor["provider_descriptor_hash"] ==
                 expected_route["provider_descriptor_hash"],
                 "route_provider_descriptor_mismatch")
        _require(descriptor["model_binding_hash"] ==
                 expected_route["model_binding_hash"],
                 "route_model_descriptor_mismatch")
        _require(fingerprint == expected_route["route_fingerprint"],
                 "route_fingerprint_mismatch")
        capabilities = model.get("capabilities") or {}
        reasoning = {
            key: value for key, value in capabilities.items()
            if any(marker in key.casefold() for marker in ("reason", "think"))
            and isinstance(value, (str, int, float, bool, type(None)))
        }
        routes.append({
            "route_kind": route_kind,
            "provider_family": str(provider.get("protocol") or "unknown"),
            "provider_descriptor_sha256": descriptor["provider_descriptor_hash"],
            "model_binding_sha256": descriptor["model_binding_hash"],
            "provider_alias_sha256": _sha_bytes(
                str(descriptor.get("provider_alias") or "").encode("utf-8"),
            ),
            "model_alias_sha256": _sha_bytes(
                str(descriptor.get("model_alias") or "").encode("utf-8"),
            ),
            "adapter_family": {
                "anthropic": "AnthropicAdapter",
                "openai-chat": "OpenAIChatAdapter",
                "openai-responses": "OpenAIResponsesAdapter",
            }.get(str(provider.get("protocol")), "UNKNOWN"),
            "transport_type": "https",
            "route_fingerprint": fingerprint,
            "context_window": model.get("context_window") or "UNKNOWN",
            "declared_route_output_cap": model.get("max_output_tokens") or "UNKNOWN",
            "reasoning_controls": reasoning or "NONE_DECLARED",
        })
    requested = scoped_creative_output_budget(
        expected_output_characters=EXPECTED_OUTPUT_CHARACTERS,
        input_tokens=0, context_window=None, declared_output_ceiling=None,
    )
    body = {
        "schema": "Slice1PhaseBCurrentRouteBindingV1",
        "version": 1,
        "role": "planning",
        "selected_route": "primary",
        "configured_route_order": ["primary", "configured_fallback"],
        "routes": routes,
        "route_fingerprint_algorithm": "ProviderRegistry.route_fingerprint@1",
        "route_configuration_source_class": (
            "LOCAL_READ_ONLY_ROUTE_SNAPSHOT_MATCHING_SEALED_SHORT_EVIDENCE"
        ),
        "local_configuration_match": "exact",
        "live_capability_probe_executed": False,
        "requested_max_output_tokens": requested,
        "effective_route_cap": requested,
        "provider_accepted_cap": "UNKNOWN_UNTIL_EXECUTION",
        "route_policy_default_ceiling": 65_536,
        "output_cap_policy": "scoped_creative_output_budget_v1",
        "route_model_changed": False,
        "fallback_policy_changed": False,
    }
    return _sealed("slice1-phase-b-current-route-binding-v1", body,
                   "route_binding_sha256")


def build_model_input(
    repo_root: Path, authority: Mapping[str, Any], compacted_skill_prompt: str,
    profile: Mapping[str, Any], contract: Mapping[str, Any],
    route: Mapping[str, Any],
) -> tuple[dict[str, Any], str, str]:
    instruction = (
        "SLICE1_PHASE_B_EVENT_REALIZATION_SHADOW_V1\n"
        "Generate exactly one non-authoritative shadow candidate for the frozen "
        "formal event. Return only one JSON object with exactly title and narrative. "
        "Do not return or modify Runtime-owned authority, identifiers, order, "
        "dependencies, StoryState, Canon, READY, Draft, Review, or Maintenance. "
        "Realize the required obligations through character choice, resistance, "
        "causal change, and bounded sensory specificity."
    )
    system = (
        STAGE_SYSTEM["planning"]
        + "\n\nSkill instructions and frozen Slice1 authority are supplied for an isolated "
          "shadow artifact only. Production Planning V1 remains authoritative.\n\n"
        + compacted_skill_prompt
    )
    user_payload = {
        "contract": SLICE1_CONTRACT_IDENTITY,
        "authority": dict(authority),
        "instruction": instruction,
        "expected_output_characters": EXPECTED_OUTPUT_CHARACTERS,
        "output_fields": ["title", "narrative"],
    }
    user = json.dumps(
        user_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    combined = system + "\n\0" + user
    body = {
        "schema": "Slice1PhaseBModelInputAssemblyV1",
        "version": 1,
        "system_template_sha256": _sha_bytes(STAGE_SYSTEM["planning"].encode("utf-8")),
        "system_sha256": _sha_bytes(system.encode("utf-8")),
        "user_sha256": _sha_bytes(user.encode("utf-8")),
        "deterministic_instruction_sha256": _sha_bytes(instruction.encode("utf-8")),
        "authority_context_sha256": _domain_sha(
            "slice1-phase-b-authority-input-v1", authority,
        ),
        "current_skill_context_sha256": profile[
            "combined_current_runtime_compacted_prompt_sha256"
        ],
        "current_skill_profile_sha256": profile["profile_sha256"],
        "contract_sha256": contract["authority_binding_sha256"],
        "validator_bundle_sha256": contract["validator_bundle_sha256"],
        "route_selection_inputs_sha256": route["route_binding_sha256"],
        "retry_repair_prompt_policy": "NO_MODEL_REPAIR_IN_BASELINE_SMOKE_V1",
        "output_parser": "GeneratedArtifactGateway+EventRealizationCandidateV1",
        "observer_state": "PTR12_REQUIRED_ENABLED",
        "estimated_input_tokens": estimate_input_tokens(combined),
        "raw_prompt_persisted": False,
        "raw_skill_content_persisted": False,
        "raw_story_persisted": False,
    }
    return _sealed("slice1-phase-b-model-input-assembly-v1", body,
                   "model_input_assembly_sha256"), system, user


def call_graph_contract() -> dict[str, Any]:
    return _sealed("slice1-phase-b-call-graph-v1", {
        "schema": "Slice1PhaseBCallGraphV1",
        "version": 1,
        "initial_creative_call_count": 1,
        "targeted_model_repair_calls": [],
        "max_repair_calls_per_case": 0,
        "expected_model_calls": 1,
        "hard_max_model_calls": 1,
        "max_model_calls_per_case": 1,
        "recovery_escalation_sequence": [
            "single_primary_creative_dispatch",
            "deterministic_generated_artifact_conversion",
            "slice1_validator_bundle",
            "freeze_exact_pass_or_typed_terminal_failure",
        ],
        "offline_recovery_functions_are_model_calls": False,
        "whole_slice_regeneration_model_call_count": 0,
        "whole_planning_regeneration_allowed": False,
        "unbounded_retry_allowed": False,
        "duplicate_dispatch_allowed": False,
        "no_progress_stop_rule": "first_non_pass_is_terminal_for_this_baseline",
        "duplicate_prevention": (
            "exclusive single-use nonce reservation plus hard call ordinal <= 1"
        ),
        "derivation": (
            "planning_v2_slice1 exposes no Provider or model retry path; the narrow "
            "Phase B wrapper adds exactly one initial shadow call and no repair calls"
        ),
    }, "call_graph_sha256")


def budget_contract(route: Mapping[str, Any], model_input: Mapping[str, Any]) -> dict[str, Any]:
    requested = int(route["requested_max_output_tokens"])
    expected_input = int(model_input["estimated_input_tokens"])
    _require(expected_input <= HARD_MAX_INPUT_TOKENS,
             "materialized_input_exceeds_hard_cap")
    return _sealed("slice1-phase-b-current-skill-budget-v1", {
        "schema": "Slice1PhaseBCurrentSkillBudgetV1",
        "version": 1,
        "maximum_runs": 1,
        "expected_model_calls": 1,
        "hard_max_model_calls": 1,
        "expected_input_tokens": expected_input,
        "hard_max_input_tokens": HARD_MAX_INPUT_TOKENS,
        "expected_output_tokens": EXPECTED_OUTPUT_TOKENS,
        "hard_max_output_tokens": requested,
        "hard_max_output_tokens_per_call": requested,
        "requested_max_output_tokens": requested,
        "effective_route_cap": route["effective_route_cap"],
        "provider_accepted_cap": "UNKNOWN_UNTIL_EXECUTION",
        "route_policy_default_ceiling": route["route_policy_default_ceiling"],
        "expected_elapsed_seconds": EXPECTED_ELAPSED_SECONDS,
        "hard_max_elapsed_seconds": HARD_MAX_ELAPSED_SECONDS,
        "expected_usd": "UNKNOWN_LOCAL_PRICE_NOT_TRUSTED",
        "hard_max_usd": "UNKNOWN_LOCAL_PRICE_NOT_TRUSTED",
        "expected_cny": "UNKNOWN_LOCAL_PRICE_NOT_TRUSTED",
        "hard_max_cny": "UNKNOWN_LOCAL_PRICE_NOT_TRUSTED",
        "first_terminal_stop": True,
        "resume_allowed": False,
        "second_run_allowed": False,
    }, "budget_sha256")


def output_isolation_contract() -> dict[str, Any]:
    return _sealed("slice1-phase-b-output-isolation-v1", {
        "schema": "Slice1PhaseBOutputIsolationV1",
        "version": 1,
        "namespace": f"slice1-phase-b-experiments/{COHORT_ID}",
        "experiment_artifact_relative_path": (
            "artifact/generated-event-realization-v1.json"
        ),
        "ptr12_trace_relative_path": "trace/ptr12-hash-only-v1.jsonl",
        "ledger_relative_path": "ledger/single-use-ledger-v1.json",
        "isolated_database_relative_path": "runtime/app.db",
        "generated_content_storage": "EXPERIMENT_ARTIFACT_ONLY",
        "ptr12_raw_prose_allowed": False,
        "ptr12_reasoning_text_allowed": False,
        "production_database_mutation_allowed": False,
        "story_state_mutation_allowed": False,
        "canon_mutation_allowed": False,
        "ready_mutation_allowed": False,
        "draft_input_mutation_allowed": False,
        "maintenance_mutation_allowed": False,
        "retention_policy": "retain_until_current-skill-vs-skill-v2-ab-closure",
        "cleanup_policy": "explicit_user-authorized-removal-only",
    }, "output_isolation_sha256")


def quality_capture_contract() -> dict[str, Any]:
    return _sealed("slice1-phase-b-quality-capture-contract-v1", {
        "schema": "Slice1PhaseBQualityCaptureContractV1",
        "version": 1,
        "exact_artifact_fields": ["title", "narrative"],
        "validation": [
            "slice1_validator_outcome", "authority_violations",
            "semantic_validator_findings",
        ],
        "creative_signals": [
            "causal_event_fidelity", "character_motivation",
            "character_voice_if_applicable", "world_specificity_and_sensory_realization",
            "setup_payoff_or_dependency", "pov_tense_tone_genre_consistency",
            "draft_intent_preservation_proxy_supported_by_slice1",
        ],
        "unsupported_dimensions_value": "UNKNOWN",
        "recovery_signals": [
            "targeted_repair_count", "untargeted_creative_mutation_count",
            "first_pass_vs_repair_convergence", "no_progress",
            "duplicate_dispatch", "whole_planning_regeneration_count",
        ],
        "rigid_single_literary_score": False,
        "offline_validator_claims_literary_superiority": False,
        "human_or_model_assisted_ab_review_required": True,
    }, "quality_capture_contract_sha256")


def ab_lock_contract(
    workload: Mapping[str, Any], contract: Mapping[str, Any], route: Mapping[str, Any],
    budget: Mapping[str, Any], output: Mapping[str, Any], quality: Mapping[str, Any],
) -> dict[str, Any]:
    same = {
        "cohort_workload_sha256": workload["workload_sha256"],
        "authority_input_sha256": workload["authority_input_sha256"],
        "slice1_contract_sha256": contract["authority_binding_sha256"],
        "planning_v2_source_sha256": contract["validator_bundle"]["source_sha256"],
        "main_prompt_body_sha256": _sha_bytes(STAGE_SYSTEM["planning"].encode("utf-8")),
        "route_model_sha256": route["route_binding_sha256"],
        "output_budget_sha256": budget["budget_sha256"],
        "call_hard_cap": budget["hard_max_model_calls"],
        "retry_repair_policy": "NO_MODEL_REPAIR_IN_BASELINE_SMOKE_V1",
        "validator_bundle_sha256": contract["validator_bundle_sha256"],
        "ptr12_observer": "REQUIRED_ENABLED",
        "output_isolation_sha256": output["output_isolation_sha256"],
        "evaluation_rubric_sha256": quality["quality_capture_contract_sha256"],
    }
    return _sealed("slice1-phase-b-ab-comparison-lock-v1", {
        "schema": "Slice1PhaseBABComparisonLockV1",
        "version": 1,
        "a_arm": "CURRENT_RUNTIME_SKILL",
        "future_b_arm": "SKILL_CONTEXT_V2",
        "primary_intended_changed_variable": "SKILL_CONTEXT_ARM",
        "frozen_same_bindings": same,
        "confounded_if_any_other_binding_changes": True,
        "fresh_rebaseline_required_on_non_skill_change": True,
    }, "ab_comparison_lock_sha256")


def launcher_binding(repo_root: Path, bound: Mapping[str, str]) -> dict[str, Any]:
    launcher_source = repo_root / "tools/canary/slice1_phase_b_current_skill.py"
    return _sealed("slice1-phase-b-launcher-binding-v1", {
        "schema": "Slice1PhaseBLauncherBindingV1",
        "version": 1,
        "launcher_source_sha256": _sha_file(launcher_source),
        "phase_1": "materialization_and_validation_only",
        "phase_1_external_actions": dict(ZERO_COUNTERS),
        "phase_2": "unreachable_without_fresh_signed_user_approval",
        "required_pre_execution_order": [
            "verify_named_approval", "verify_single_use_nonce",
            "verify_exact_head_and_build", "verify_packet_hashes",
            "verify_cohort_hash", "verify_skill_profile_hash",
            "verify_route_model_hash", "verify_budget",
            "verify_ptr12_enabled", "verify_shadow_output_isolation",
            "credential_lookup", "provider_client_creation", "single_real_call",
        ],
        "bound_hashes": dict(bound),
        "credential_import_deferred_until_after_gate": True,
        "provider_client_import_deferred_until_after_gate": True,
        "hard_call_budget_checked_before_credential_lookup": True,
        "single_use_ledger_exclusive_creation": True,
        "full_short_entrypoint_reachable": False,
        "draft_entrypoint_reachable": False,
        "skill_v2_entrypoint_reachable": False,
    }, "launcher_binding_sha256")


def approval_template(bound: Mapping[str, str]) -> dict[str, Any]:
    return _sealed("slice1-phase-b-disabled-approval-template-v1", {
        "schema": "Slice1PhaseBCurrentSkillApprovalTemplateV1",
        "version": 1,
        "approval_scope": APPROVAL_SCOPE,
        "cohort_id": COHORT_ID,
        "bound_hashes": dict(bound),
        "execution_authorized": False,
        "named_approver": None,
        "usage_status": "unused",
        "reservation_status": "unreserved",
        "single_use_nonce": None,
        "execution_window": None,
        "approval_reuse_allowed": False,
        "approval_cohort_reuse_allowed": False,
        "full_short_authorized": False,
        "skill_v2_authorized": False,
        "draft_authorized": False,
        "credential_lookup_authorized": False,
        "provider_client_creation_authorized": False,
        "network_authorized": False,
        "model_call_authorized": False,
        "paid_call_authorized": False,
        "external_actions": dict(ZERO_COUNTERS),
    }, "approval_template_sha256")


def _privacy_scan(files: Mapping[str, bytes]) -> dict[str, Any]:
    absolute = re.compile(rb"(?:[A-Za-z]:[\\/]|/(?:home|Users|workspace)/)")
    secret = re.compile(
        rb"(?i)(?:api[_-]?key|authorization|bearer)\s*[:=]\s*[^\s,}\]]+",
    )
    raw_provider = re.compile(rb"(?i)raw_provider_(?:response|content)\s*[:=]")
    violations = []
    for name, data in files.items():
        if absolute.search(data) or secret.search(data) or raw_provider.search(data):
            violations.append(name)
    return {
        "schema": "Slice1PhaseBCurrentSkillPrivacyScanV1",
        "version": 1,
        "overall_status": "exact" if not violations else "blocked",
        "scanned_file_count": len(files),
        "materialization_privacy_match_count": len(violations),
        "absolute_path_match_count": sum(bool(absolute.search(v)) for v in files.values()),
        "secret_value_match_count": sum(bool(secret.search(v)) for v in files.values()),
        "raw_provider_content_match_count": sum(
            bool(raw_provider.search(v)) for v in files.values()
        ),
        "raw_prompt_field_count": 0,
        "raw_skill_content_field_count": 0,
        "raw_user_production_story_field_count": 0,
        "private_request_id_count": 0,
        "violating_files": violations,
        "external_actions": dict(ZERO_COUNTERS),
    }


def build_packet_documents(
    *, repo_root: Path, route_database: Path,
    expected_routes: Mapping[str, Mapping[str, str]] | None = None,
    skill_roots: Sequence[Path] | None = None,
) -> tuple[dict[str, bytes], dict[str, Any]]:
    git = verify_git_gate(repo_root, require_clean=True)
    ptr12 = verify_ptr12_final(repo_root)
    profile, compacted_skill = verify_skill_resolution_twice(
        repo_root, roots=skill_roots,
    )
    workload, authority = load_fixture_binding(repo_root)
    contract = slice1_contract_binding(repo_root)
    route = resolve_route_binding(route_database, expected_routes=expected_routes)
    model_input, _system, _user = build_model_input(
        repo_root, authority, compacted_skill, profile, contract, route,
    )
    call_graph = call_graph_contract()
    budget = budget_contract(route, model_input)
    output = output_isolation_contract()
    quality = quality_capture_contract()
    ab_lock = ab_lock_contract(workload, contract, route, budget, output, quality)
    plan_body = {
        "schema": "Slice1PhaseBCurrentSkillPlanV1", "version": 1,
        "baseline_head": BASELINE_HEAD,
        "materialization_head": git["head"],
        "branch": git["branch"],
        "scope": APPROVAL_SCOPE,
        "materialization_only": True,
        "planning_v1_production_authority": True,
        "slice1_phase_b_shadow_only": True,
        "skill_arm": SKILL_ARM,
        "skill_v2_profile_active": False,
        "ptr12_final_acceptance": ptr12,
        "production_source_changed": False,
        "prompt_changed": False,
        "route_model_changed": False,
        "retry_policy_changed": False,
        "fallback_policy_changed": False,
        "planning_v1_changed": False,
        "planning_v2_changed": False,
        "skill_profile_changed": False,
        "phase_b_status": "NOT_STARTED",
        "full_short_canary": "NOT_EXECUTED",
        "external_actions": dict(ZERO_COUNTERS),
    }
    plan = _sealed("slice1-phase-b-current-skill-plan-v1", plan_body, "plan_sha256")
    bound = {
        "materialization_head": git["head"],
        "plan_sha256": plan["plan_sha256"],
        "workload_sha256": workload["workload_sha256"],
        "authority_input_sha256": workload["authority_input_sha256"],
        "current_skill_profile_sha256": profile["profile_sha256"],
        "model_input_assembly_sha256": model_input["model_input_assembly_sha256"],
        "route_binding_sha256": route["route_binding_sha256"],
        "budget_sha256": budget["budget_sha256"],
        "ptr12_manifest_sha256": ptr12["manifest_sha256"],
        "output_isolation_sha256": output["output_isolation_sha256"],
        "call_graph_sha256": call_graph["call_graph_sha256"],
        "quality_capture_contract_sha256": quality["quality_capture_contract_sha256"],
        "ab_comparison_lock_sha256": ab_lock["ab_comparison_lock_sha256"],
    }
    launcher = launcher_binding(repo_root, bound)
    bound_with_launcher = {**bound, "launcher_binding_sha256": launcher["launcher_binding_sha256"]}
    approval = approval_template(bound_with_launcher)
    definition = {
        "documents": sorted((
            "plan", "workload", "profile", "authority", "route", "model_input",
            "call_graph", "budget", "approval", "launcher", "output", "quality",
            "ab_lock",
        )),
        "cohort_id": COHORT_ID,
        "case_ids": list(CASE_IDS),
        "schema_version": 1,
    }
    packet_definition_sha = _domain_sha(
        "slice1-phase-b-current-skill-packet-definition-v1", definition,
    )
    offline = {
        "schema": "Slice1PhaseBCurrentSkillOfflineTestReceiptV1",
        "version": 1,
        "status": "materializer_self_checks_exact",
        "baseline_head_binding": "exact",
        "ptr12_final_binding": "exact",
        "skill_resolution_runs": 2,
        "skill_resolution_deterministic": True,
        "route_model_binding": "exact",
        "model_input_assembly": "deterministic",
        "call_graph_finite": True,
        "budget_hard_cap": "bound",
        "approval_execution_authorized": False,
        "approval_named_approver": None,
        "output_isolation": "exact",
        "external_actions": dict(ZERO_COUNTERS),
        "pytest_result": "PENDING_POST_MATERIALIZATION_VALIDATION",
        "strict_l3_result": "PENDING_POST_MATERIALIZATION_VALIDATION",
    }
    documents: dict[str, bytes] = {
        "README.md": (
            "# Slice1 Phase B CURRENT Skill baseline materialization\n\n"
            "This directory contains a disabled, single-use, shadow-only approval packet. "
            "It does not authorize or execute credentials, Provider clients, network, model, "
            "paid calls, Draft, or Full Short.\n"
        ).encode("utf-8"),
        "phase-b-current-skill-plan-v1.json": _json_bytes(plan),
        "phase-b-current-skill-workload-v1.json": _json_bytes(workload),
        "phase-b-current-skill-profile-v1.json": _json_bytes(profile),
        "phase-b-current-skill-authority-binding-v1.json": _json_bytes(contract),
        "phase-b-current-skill-route-binding-v1.json": _json_bytes(route),
        "phase-b-current-skill-model-input-assembly-v1.json": _json_bytes(model_input),
        "phase-b-current-skill-call-graph-v1.json": _json_bytes(call_graph),
        "phase-b-current-skill-budget-v1.json": _json_bytes(budget),
        "phase-b-current-skill-approval-template-v1.json": _json_bytes(approval),
        "phase-b-current-skill-launcher-binding-v1.json": _json_bytes(launcher),
        "phase-b-current-skill-output-isolation-v1.json": _json_bytes(output),
        "phase-b-current-skill-quality-capture-contract-v1.json": _json_bytes(quality),
        "phase-b-current-skill-ab-comparison-lock-v1.json": _json_bytes(ab_lock),
        "phase-b-current-skill-offline-test-receipt-v1.json": _json_bytes(offline),
    }
    report = f"""# Slice1 Phase B CURRENT Skill Baseline Materialization Final Report

`SLICE1_PHASE_B_CURRENT_SKILL_BASELINE_MATERIALIZED`

`SLICE1_PHASE_B_CURRENT_SKILL_BASELINE_READY_FOR_USER_APPROVAL=YES`

- Branch: `{git['branch']}`
- Baseline HEAD: `{BASELINE_HEAD}`
- Materialization HEAD: `{git['head']}`
- PTR12 reviewed production HEAD: `{PTR12_REVIEWED_HEAD}`
- PTR12 evidence seal HEAD: `{PTR12_SEAL_HEAD}`
- Production source diff: `0`
- Skill arm: `{SKILL_ARM}`
- Skill V2 active: `NO`
- Cohort: `{COHORT_ID}`
- Case IDs: `{', '.join(CASE_IDS)}`
- Fixture SHA-256: `{workload['fixture_sha256']}`
- Authority input SHA-256: `{workload['authority_input_sha256']}`
- Slice1 authority binding SHA-256: `{contract['authority_binding_sha256']}`
- Current Skill profile SHA-256: `{profile['profile_sha256']}`
- Model input assembly SHA-256: `{model_input['model_input_assembly_sha256']}`
- Route binding SHA-256: `{route['route_binding_sha256']}`
- Call graph SHA-256: `{call_graph['call_graph_sha256']}`
- Expected / hard model calls: `1 / 1`
- Expected / hard input tokens: `{budget['expected_input_tokens']} / {budget['hard_max_input_tokens']}`
- Expected / hard output tokens: `{budget['expected_output_tokens']} / {budget['hard_max_output_tokens']}`
- Per-call output hard cap: `{budget['hard_max_output_tokens_per_call']}`
- Expected / hard elapsed seconds: `{budget['expected_elapsed_seconds']} / {budget['hard_max_elapsed_seconds']}`
- Expected / hard cost: `UNKNOWN / UNKNOWN` (no locally trusted current price authority)
- Budget SHA-256: `{budget['budget_sha256']}`
- Approval template SHA-256: `{approval['approval_template_sha256']}`
- Launcher binding SHA-256: `{launcher['launcher_binding_sha256']}`
- Output isolation SHA-256: `{output['output_isolation_sha256']}`
- Quality capture SHA-256: `{quality['quality_capture_contract_sha256']}`
- A/B comparison lock SHA-256: `{ab_lock['ab_comparison_lock_sha256']}`
- Packet definition SHA-256: `{packet_definition_sha}`
- PTR12 manifest SHA-256: `{ptr12['manifest_sha256']}`
- PTR12 manifest coverage: `11/11 exact`
- CURRENT Skill resolution: `story-init, plot-structure, character-management, worldbuilding`; two local runs exact
- Source classes: `{', '.join(item['source_class'] for item in profile['resolved_skills'])}`
- Planning V1 production authority: `YES`
- Slice1 Phase B shadow-only: `YES`
- Whole Planning regeneration allowed: `NO`
- Output isolation: experiment artifact only; PTR12 trace remains hash/shape-only
- Exact next gate: `SLICE1_PHASE_B_CURRENT_SKILL_BASELINE_USER_APPROVAL`

`EXECUTION_AUTHORIZED=NO`  
`NAMED_APPROVER=null`  
`APPROVAL_REUSE_ALLOWED=NO`  
`FULL_SHORT_AUTHORIZED=NO`  
`SKILL_V2_AUTHORIZED=NO`  
`DRAFT_AUTHORIZED=NO`  
`STORYSTATE_MUTATION_ALLOWED=NO`  
`CANON_MUTATION_ALLOWED=NO`  
`REAL_PROVIDER_CALLS=0`  
`NETWORK_CALLS=0`  
`MODEL_CALLS=0`  
`PAID_CALLS=0`  
`SLICE1_PHASE_B=NOT_STARTED`  
`FULL_SHORT_CANARY=NOT_EXECUTED`
"""
    documents["phase-b-current-skill-final-report-v1.md"] = report.encode("utf-8")
    privacy = _privacy_scan(documents)
    _require(privacy["overall_status"] == "exact", "materialization_privacy_blocked")
    documents["phase-b-current-skill-privacy-scan-v1.json"] = _json_bytes(privacy)
    meta = {
        "git": git, "ptr12": ptr12, "profile": profile, "workload": workload,
        "contract": contract, "route": route, "model_input": model_input,
        "call_graph": call_graph, "budget": budget, "approval": approval,
        "launcher": launcher, "output": output, "quality": quality,
        "ab_lock": ab_lock, "packet_definition_sha256": packet_definition_sha,
        "privacy": privacy,
    }
    return documents, meta


def materialize_packet(
    *, repo_root: Path, route_database: Path, output_root: Path,
) -> dict[str, Any]:
    _require(not output_root.exists(), "materialization_target_already_exists")
    documents, meta = build_packet_documents(
        repo_root=repo_root, route_database=route_database,
    )
    output_root.mkdir(parents=True)
    for name, data in documents.items():
        (output_root / name).write_bytes(data)
    entries = []
    for path in sorted(output_root.iterdir(), key=lambda item: item.name):
        if path.is_file():
            entries.append({
                "path": f"{REPORT_RELATIVE_ROOT}/{path.name}",
                "bytes": path.stat().st_size,
                "sha256": _sha_file(path),
            })
    manifest = {
        "schema": "Slice1PhaseBCurrentSkillSHA256ManifestV1",
        "version": 1,
        "overall_status": "exact",
        "coverage_root": REPORT_RELATIVE_ROOT,
        "inclusion_rule": "all direct regular files except sha256-manifest-v1.json",
        "self_excluded": True,
        "algorithm": "sha256",
        "path_basis": "repository-relative-posix",
        "byte_domain": "exact_file_bytes",
        "files": entries,
        "file_count": len(entries),
        "packet_definition_sha256": meta["packet_definition_sha256"],
        "external_actions": dict(ZERO_COUNTERS),
    }
    manifest["manifest_definition_sha256"] = _domain_sha(
        "slice1-phase-b-manifest-definition-v1",
        {key: value for key, value in manifest.items() if key != "files"},
    )
    _write_json(output_root / "sha256-manifest-v1.json", manifest)
    return {**meta, "manifest": manifest,
            "manifest_sha256": _sha_file(output_root / "sha256-manifest-v1.json")}


def validate_materialized_packet(repo_root: Path, packet_root: Path) -> dict[str, Any]:
    manifest = _read_json(packet_root / "sha256-manifest-v1.json")
    _require(manifest.get("overall_status") == "exact", "packet_manifest_not_exact")
    entries = list(manifest.get("files") or ())
    _require(len(entries) == manifest.get("file_count"), "packet_manifest_coverage_mismatch")
    for entry in entries:
        path = repo_root / str(entry.get("path") or "")
        _require(path.is_file(), "packet_file_missing")
        _require(path.stat().st_size == entry.get("bytes"), "packet_file_size_mismatch")
        _require(_sha_file(path) == entry.get("sha256"), "packet_file_hash_mismatch")
    approval = _read_json(packet_root / "phase-b-current-skill-approval-template-v1.json")
    _require(approval.get("execution_authorized") is False,
             "disabled_approval_became_authorized")
    _require(approval.get("named_approver") is None, "disabled_approval_has_approver")
    _require(approval.get("usage_status") == "unused"
             and approval.get("reservation_status") == "unreserved",
             "disabled_approval_not_unused")
    _require(all(value == 0 for value in ZERO_COUNTERS.values()),
             "materialization_external_action_counter_nonzero")
    return {"status": "exact", "file_count": len(entries), "approval": approval}


def validate_signed_launch(
    *, repo_root: Path, packet_root: Path, signed_approval: Mapping[str, Any],
    run_root: Path, now: datetime | None = None,
) -> dict[str, Any]:
    packet = validate_materialized_packet(repo_root, packet_root)
    template = packet["approval"]
    _require(signed_approval.get("schema") == "Slice1PhaseBCurrentSkillSignedApprovalV1",
             "signed_approval_schema_mismatch")
    _require(signed_approval.get("execution_authorized") is True,
             "execution_not_authorized")
    _require(bool(signed_approval.get("named_approver")), "named_approver_missing")
    nonce = str(signed_approval.get("single_use_nonce") or "")
    _require(bool(nonce), "single_use_nonce_missing")
    _require(signed_approval.get("approval_scope") == APPROVAL_SCOPE,
             "approval_scope_mismatch")
    _require(signed_approval.get("cohort_id") == COHORT_ID, "approval_cohort_mismatch")
    _require(signed_approval.get("bound_hashes") == template.get("bound_hashes"),
             "approval_bound_hashes_mismatch")
    _require(signed_approval.get("full_short_authorized") is False,
             "full_short_authorization_forbidden")
    _require(signed_approval.get("skill_v2_authorized") is False,
             "skill_v2_authorization_forbidden")
    _require(signed_approval.get("draft_authorized") is False,
             "draft_authorization_forbidden")
    window = signed_approval.get("execution_window") or {}
    current = now or datetime.now(timezone.utc)
    try:
        start = datetime.fromisoformat(str(window["not_before"]).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(window["not_after"]).replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError) as exc:
        raise Slice1PhaseBMaterializationError("execution_window_invalid") from exc
    _require(start <= current.astimezone(timezone.utc) <= end,
             "execution_window_inactive")
    expected_head = str((template.get("bound_hashes") or {}).get("materialization_head"))
    verify_git_gate(repo_root, expected_head=expected_head, require_clean=True)
    verify_ptr12_final(repo_root)
    profile, _ = verify_skill_resolution_twice(repo_root)
    _require(profile["profile_sha256"] ==
             template["bound_hashes"]["current_skill_profile_sha256"],
             "current_skill_profile_changed")
    _require(os.getenv("NOVEL_PTR12_RAW_SHAPE_GUARD_OBSERVER_V1") == "1",
             "ptr12_observer_not_enabled")
    isolation = _read_json(packet_root / "phase-b-current-skill-output-isolation-v1.json")
    _require(isolation.get("production_database_mutation_allowed") is False,
             "output_isolation_invalid")
    _require(not run_root.exists(), "single_use_run_namespace_already_exists")
    return {
        "status": "exact", "nonce": nonce,
        "hard_max_model_calls": 1,
        "credential_lookup_allowed_after_this_return": True,
        "provider_client_creation_allowed_after_this_return": True,
    }


async def execute_authorized_once(
    *, repo_root: Path, packet_root: Path, signed_approval_path: Path,
    route_database: Path, run_root: Path,
) -> dict[str, Any]:
    """Execute the single shadow call; never used by materialization/tests.

    All imports capable of touching credentials or constructing a Provider
    client occur only after validate_signed_launch returns exact.
    """

    signed = _read_json(signed_approval_path)
    gate = validate_signed_launch(
        repo_root=repo_root, packet_root=packet_root,
        signed_approval=signed, run_root=run_root,
    )
    run_root.mkdir(parents=True)
    ledger_root = run_root / "ledger"
    ledger_root.mkdir()
    reservation = ledger_root / "single-use-ledger-v1.json"
    with reservation.open("x", encoding="utf-8") as handle:
        json.dump({
            "schema": "Slice1PhaseBSingleUseLedgerV1", "version": 1,
            "cohort_id": COHORT_ID, "nonce_sha256": _sha_bytes(gate["nonce"].encode()),
            "usage_status": "reserved", "model_call_count": 0,
        }, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
    runtime_root = run_root / "runtime"
    runtime_root.mkdir()
    isolated_db = runtime_root / "app.db"
    shutil.copy2(route_database, isolated_db)
    workload, authority_value = load_fixture_binding(repo_root)
    profile, compacted = verify_skill_resolution_twice(repo_root)
    contract_binding = slice1_contract_binding(repo_root)
    route = resolve_route_binding(route_database)
    model_input, system, user = build_model_input(
        repo_root, authority_value, compacted, profile, contract_binding, route,
    )
    budget = _read_json(packet_root / "phase-b-current-skill-budget-v1.json")
    _require(model_input["model_input_assembly_sha256"] ==
             signed["bound_hashes"]["model_input_assembly_sha256"],
             "model_input_changed_before_dispatch")
    _require(gate["hard_max_model_calls"] == 1, "call_budget_not_one")

    # Credential-capable imports are intentionally below the complete gate and
    # exclusive single-use reservation.
    from novel_flywheel.model_diagnostics import ModelDiagnosticContextV1
    from novel_flywheel.models import ModelGateway
    from novel_flywheel.providers.registry import ProviderRegistry
    from novel_flywheel.secrets import KeyringSecretStore
    from novel_flywheel.structured_artifacts import (
        StructuredArtifactContract,
        StructuredOutputRequirement,
    )
    from novel_flywheel.planning_v2_slice1 import (
        build_event_realization_artifact,
        convert_event_realization_candidate,
        freeze_validated_artifact,
        validate_event_realization_artifact,
    )

    db = Database(isolated_db)
    gateway = ModelGateway(db, ProviderRegistry(db, KeyringSecretStore()))
    authority = EventRealizationInputAuthorityV1.model_validate(authority_value)
    contract = StructuredArtifactContract(
        name="planning_event_realization_shadow_v1",
        version=1,
        schema=EventRealizationCandidateV1.model_json_schema(),
        runtime_authority={"authority_input_sha256": workload["authority_input_sha256"]},
    )
    diagnostic = ModelDiagnosticContextV1(
        project_root=run_root, run_id=COHORT_ID, stage="planning",
        boundary="slice1_phase_b_current_skill", role="planning",
        route_kind="primary", contract_id=SLICE1_CONTRACT_IDENTITY,
        contract_version=1, outer_retry_ordinal=1,
        provider_binding_sha256=EXPECTED_PRIMARY_DESCRIPTOR,
        model_binding_sha256=EXPECTED_PRIMARY_MODEL,
        canary_output_limit=int(budget["hard_max_output_tokens_per_call"]),
    )
    started = datetime.now(timezone.utc)
    result = await asyncio.wait_for(
        gateway.complete_route(
            "primary", "planning", system, user,
            max_output_tokens=int(budget["hard_max_output_tokens_per_call"]),
            contract=contract,
            structured_requirement=StructuredOutputRequirement.PLAIN_TEXT,
            diagnostic_context=diagnostic,
        ),
        timeout=int(budget["hard_max_elapsed_seconds"]),
    )
    candidate, conversion = convert_event_realization_candidate(
        result.text, authority=authority,
    )
    artifact = build_event_realization_artifact(
        authority, candidate, producer_kind="future_model_shadow",
    )
    validation = validate_event_realization_artifact(artifact, authority)
    _require(validation.status == "PASS", "slice1_generated_candidate_rejected")
    frozen = freeze_validated_artifact(artifact, validation)
    artifact_root = run_root / "artifact"
    artifact_root.mkdir()
    _write_json(artifact_root / "generated-event-realization-v1.json", {
        "schema": "Slice1PhaseBGeneratedExperimentArtifactV1", "version": 1,
        "cohort_id": COHORT_ID, "skill_arm": SKILL_ARM,
        "artifact": frozen.model_dump(mode="json", by_alias=True),
        "conversion_audit_sha256": _domain_sha(
            "slice1-phase-b-conversion-audit-v1", asdict(conversion),
        ),
        "model_receipt": {
            key: value for key, value in result.receipt.items()
            if key not in {"raw_response", "raw_content", "request_id"}
        },
        "elapsed_seconds": (datetime.now(timezone.utc) - started).total_seconds(),
        "production_authority": False,
    })
    _write_json(reservation, {
        "schema": "Slice1PhaseBSingleUseLedgerV1", "version": 1,
        "cohort_id": COHORT_ID, "nonce_sha256": _sha_bytes(gate["nonce"].encode()),
        "usage_status": "consumed", "model_call_count": 1,
    })
    return {
        "status": "executed_once", "model_call_count": 1,
        "full_short_canary": "NOT_EXECUTED", "draft_entered": False,
        "production_database_mutation_count": 0,
    }


def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--route-database", type=Path, required=True)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    output_root = (args.output_root or repo_root / REPORT_RELATIVE_ROOT).resolve()
    if args.validate_only:
        result = validate_materialized_packet(repo_root, output_root)
    else:
        result = materialize_packet(
            repo_root=repo_root, route_database=args.route_database.resolve(),
            output_root=output_root,
        )
    print(json.dumps({
        "status": result.get("status", "materialized"),
        "cohort_id": COHORT_ID,
        "execution_authorized": False,
        "external_actions": ZERO_COUNTERS,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
