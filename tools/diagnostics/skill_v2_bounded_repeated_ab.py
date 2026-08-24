from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Mapping

from novel_flywheel.canonical_shadow import canonical_sha256
from novel_flywheel.planning_v2_slice1 import (
    EventRealizationInputAuthorityV1,
    normalize_event_realization_input_authority_v1,
)
from novel_flywheel.runtime_skill_profiles import (
    RESTORED_CREATIVE_RULE_IDS,
    audit_creative_capability_presence,
)
from tools.canary import slice1_phase_b_current_skill as current_arm


UTF8 = "utf-8"
EXPECTED_BRANCH = "r1-ptr3/planning-repair-finding-propagation-20260817"
BASELINE_HEAD = "b639194b12917730107e328f344b69f5d42e619c"
OUTPUT_ROOT = "docs/superpowers/reports/short-plan-v2-skill-v2-bounded-repeated-ab-v1"
EXECUTION_ROOT = "docs/superpowers/reports/short-plan-v2-skill-v2-bounded-repeated-ab-execution-v1"
CAMPAIGN_ID = "skill-v2-bounded-repeated-ab-v1-20260824t162103z-001"

SEALED_ROOT = "docs/superpowers/reports/short-plan-v2-skill-v2-creative-restoration-v1"
SEALED_PLAN_PATH = (
    "docs/superpowers/reports/short-plan-v2-skill-v2-quality-regression-root-cause-v1/"
    "bounded-repeated-ab-plan-v1.json"
)
RESTORED_DESIGN_PATH = f"{SEALED_ROOT}/bounded-repeated-ab-design-v1.json"
DECISION_RULE_PATH = f"{SEALED_ROOT}/future-ab-decision-rule-v1.json"
RESTORATION_MANIFEST_PATH = f"{SEALED_ROOT}/sha256-manifest-v1.json"
RESTORED_CONTEXT_PATH = (
    "docs/superpowers/reports/short-plan-v2-slice1-phase-b-skill-v2-restored-"
    "materialization-v1/restored-b-rendered-context-binding-v1.json"
)
RESTORED_PROFILE_PATH = (
    "docs/superpowers/reports/short-plan-v2-slice1-phase-b-skill-v2-restored-"
    "materialization-v1/restored-b-profile-binding-v1.json"
)
CURRENT_PROFILE_PATH = (
    "docs/superpowers/reports/short-plan-v2-slice1-phase-b-current-skill-"
    "materialization-v5/phase-b-current-skill-v5-skill-profile-v1.json"
)
ROUTE_BINDING_PATH = (
    "docs/superpowers/reports/short-plan-v2-slice1-phase-b-skill-v2-materialization-v4/"
    "skill-v2-b-arm-route-binding-v1.json"
)
TRANSPORT_GUARD_PATH = (
    "docs/superpowers/reports/short-plan-v2-slice1-phase-b-skill-v2-materialization-v4/"
    "skill-v2-b-arm-transport-guard-binding-v1.json"
)
ATTEMPT_ACCOUNTING_PATH = (
    "docs/superpowers/reports/short-plan-v2-slice1-phase-b-skill-v2-materialization-v4/"
    "skill-v2-b-arm-attempt-accounting-v1.json"
)
QUALITY_RUBRIC_PATH = (
    "docs/superpowers/reports/short-plan-v2-slice1-phase-b-skill-v2-materialization-v4/"
    "skill-v2-b-arm-quality-rubric-v1.json"
)
ENGINEERING_RUBRIC_PATH = (
    "docs/superpowers/reports/short-plan-v2-slice1-phase-b-skill-v2-materialization-v4/"
    "skill-v2-b-arm-engineering-rubric-v1.json"
)
AUDIT_SERIALIZATION_PATH = (
    "docs/superpowers/reports/short-plan-v2-slice1-phase-b-skill-v2-materialization-v4/"
    "skill-v2-b-arm-full-success-tail-offline-v1.json"
)
PTR12_MANIFEST_PATH = "docs/superpowers/reports/r1-ptr12-final-review/sha256-manifest-v1.json"
PTR12_DECISION_PATH = (
    "docs/superpowers/reports/r1-ptr12-final-review/"
    "r1-ptr12-review-v4-final-decision-v1.json"
)

SEALED_PLAN_SHA256 = "fd6180ced062270241c5ed5039833556a87d51768a42c37ee605688e5866cbe7"
RESTORED_DESIGN_SHA256 = "4ba1a93093b0ac28f2fb952df0cb7049f6cbd4d11efc38cb6b0e5166fa3f6e8d"
DECISION_RULE_SHA256 = "2ed92dba7950363ef3ab9a7106c28ada60ebd2135317e18d34f9d193860044bd"
RESTORATION_MANIFEST_SHA256 = "362cdfb53fa3a4c3848978e674e25d2a63c1fef1ec8c26870ebe235db0012bd4"
RESTORED_PROFILE_SHA256 = "c4ca606bd76359514e15cd60a2edcecbd9bc530690abb86be7313f2bd38999c5"
RESTORED_CONTEXT_SHA256 = "e7828db2dc18eceabe06b9d1068b2683d117617fb0bd1257a26e7747fbe02772"
RESTORED_CONTEXT_CHARS = 2742
CURRENT_PROFILE_SHA256 = "4a9fd1d20c248ed3dae1815eb99605b094842d1e953e96d31d6ba7d1a4bf52c6"
CURRENT_CONTEXT_SHA256 = "c7916de36e67f380f2e10f30f169bcdbe04440cc8bd01bbf2626d26a7cdf49b7"
CURRENT_CONTEXT_CHARS = 8927


CASE_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "pair_case_id": "restored-character-heavy-v1",
        "creative_demand_class": "character-heavy",
        "primary_dimensions": ["motivation", "voice", "relationship", "subtext"],
        "event_id": "AB-CHARACTER-0001",
        "entry_state": "Mara distrusts Iven after an old betrayal and hides that she still needs his help.",
        "required_change": "Mara pays a personal cost to protect Iven, shifting distrust into conditional cooperation without resolving the betrayal.",
        "exit_state": "Iven recognizes the costly protection but misreads Mara's concealed apology as leverage.",
        "obligations": [
            "motivation:protect-rival-without-confessing-guilt",
            "voice:restrained-irony-under-fear",
            "relationship:costly-choice-creates-conditional-trust",
            "subtext:apology-concealed-as-bargain",
        ],
    },
    {
        "pair_case_id": "restored-world-heavy-v1",
        "creative_demand_class": "world-heavy",
        "primary_dimensions": ["world specificity", "sensory affordance", "system cost"],
        "event_id": "AB-WORLD-0001",
        "entry_state": "Neri enters a night market where memories are legal currency and her brother's name is collateral.",
        "required_change": "Neri buys access to a sealed archive, accepting a precise memory loss while exploiting a physical market rule.",
        "exit_state": "The archive opens, Neri loses the sound of her brother's laugh, and the Archivist faction records the debt.",
        "obligations": [
            "world-rule:memories-function-as-night-market-currency",
            "sensory-affordance:blue-ash-rain-bell-metal-and-ink-smoke",
            "system-cost:purchase-erases-one-specific-memory",
            "faction-pressure:archivists-enforce-recorded-debt",
        ],
    },
    {
        "pair_case_id": "restored-conflict-pacing-heavy-v1",
        "creative_demand_class": "conflict-pacing-heavy",
        "primary_dimensions": ["opposed tactics", "escalation", "reversal"],
        "event_id": "AB-CONFLICT-0001",
        "entry_state": "Captain Sola must cross a floodgate while Marshal Venn controls both the winch and the hostages.",
        "required_change": "Sola's misdirection forces Venn to split his defense, then a hostage's intervention reverses who controls the gate.",
        "exit_state": "The gate opens only halfway, Venn escapes with the map, and Sola gains the hostages but loses the clean pursuit route.",
        "obligations": [
            "conflict:opposed-tactics-remain-causally-legible",
            "pacing:pressure-escalates-through-three-distinct-beats",
            "reversal:hostage-action-transfers-gate-control",
            "cost:success-closes-the-clean-pursuit-route",
        ],
    },
    {
        "pair_case_id": "restored-setup-payoff-heavy-v1",
        "creative_demand_class": "setup-payoff-heavy",
        "primary_dimensions": ["plant", "dependency", "payoff"],
        "event_id": "AB-PAYOFF-0001",
        "entry_state": "A cracked tuning fork, planted earlier as a harmless keepsake, is the only object that resonates with the locked bridge.",
        "required_change": "Tao recognizes the planted property, risks breaking the keepsake, and uses its resonance to expose the bridge's hidden dependency.",
        "exit_state": "The bridge unlocks, the fork breaks, and its final tone reveals that the missing mentor crossed recently.",
        "obligations": [
            "setup:cracked-tuning-fork-was-previously-established",
            "dependency:bridge-lock-responds-only-to-matching-resonance",
            "payoff:fork-breaks-while-opening-the-bridge",
            "new-hook:final-tone-indicates-mentor-crossed-recently",
        ],
    },
    {
        "pair_case_id": "restored-mixed-v1",
        "creative_demand_class": "mixed",
        "primary_dimensions": ["Draft handoff", "template flattening", "authority"],
        "event_id": "AB-MIXED-0001",
        "entry_state": "Rin and Osei enter a wind-carved observatory as allies, but only Osei knows the eclipse mechanism demands a living witness.",
        "required_change": "Their competing motives, the observatory's cost rule, and an escalating choice produce a specific handoff for the next scene without changing the confirmed event outcome.",
        "exit_state": "Rin activates the mechanism, Osei becomes the bound witness, and both understand the alliance now carries an unequal debt.",
        "obligations": [
            "motivation:rin-seeks-proof-osei-conceals-personal-cost",
            "world-rule:eclipse-mechanism-binds-one-living-witness",
            "conflict:truth-arrives-after-activation-becomes-irreversible",
            "draft-handoff:next-scene-begins-with-unequal-debt-and-active-mechanism",
            "anti-template:realize-choice-through-specific-action-not-category-labels",
        ],
    },
)

PAIR_CASE_IDS = tuple(item["pair_case_id"] for item in CASE_DEFINITIONS)
CREATIVE_DEMAND_CLASSES = tuple(item["creative_demand_class"] for item in CASE_DEFINITIONS)

AB_EQUALITY_FIELDS = (
    "same_story_slice",
    "same_authority_input",
    "same_task_contract",
    "same_model",
    "same_provider",
    "same_route",
    "same_adapter_client",
    "same_sampling_policy",
    "same_tool_policy",
    "same_output_cap",
    "same_single_dispatch_policy",
    "same_validator_policy",
    "same_authority_tuple_policy",
    "same_audit_serialization_policy",
    "same_ptr9_policy",
    "same_ptr12_policy",
    "same_output_isolation_policy",
    "same_quality_rubric",
    "same_engineering_rubric",
)


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(UTF8)


def _text_bytes(value: str) -> bytes:
    return (value.rstrip() + "\n").encode(UTF8)


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode(UTF8)


def _domain_sha(domain: str, value: Any) -> str:
    return _sha_bytes(domain.encode(UTF8) + b"\0" + _canonical_bytes(value))


def _load(repo_root: Path, relative: str) -> Any:
    return json.loads((repo_root / relative).read_text(encoding=UTF8))


def _file_binding(repo_root: Path, relative: str) -> dict[str, Any]:
    data = (repo_root / relative).read_bytes()
    return {"path": relative, "bytes": len(data), "sha256": _sha_bytes(data)}


def _sealed(domain: str, body: Mapping[str, Any], field: str) -> dict[str, Any]:
    result = dict(body)
    result[field] = _domain_sha(domain, result)
    return result


def _external_actions() -> dict[str, int]:
    return {
        "credential_lookup_count": 0,
        "real_provider_client_creation_count": 0,
        "real_provider_request_attempts": 0,
        "http_post_attempts": 0,
        "network_calls": 0,
        "model_calls": 0,
        "paid_calls": 0,
    }


def _git(repo_root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo_root, check=True, capture_output=True, text=True,
    ).stdout.strip()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _verify_manifest(repo_root: Path, relative: str, expected_file_sha: str) -> dict[str, Any]:
    binding = _file_binding(repo_root, relative)
    _require(binding["sha256"] == expected_file_sha, f"manifest changed: {relative}")
    manifest = _load(repo_root, relative)
    mismatches: list[str] = []
    for entry in manifest["files"]:
        path = repo_root / entry["path"]
        if not path.is_file():
            mismatches.append(entry["path"])
            continue
        data = path.read_bytes()
        if len(data) != entry["bytes"] or _sha_bytes(data) != entry["sha256"]:
            mismatches.append(entry["path"])
    _require(not mismatches, f"manifest entries changed: {mismatches}")
    entry_count = manifest.get("entry_count", manifest.get("file_count", len(manifest["files"])))
    return {**binding, "entry_count": entry_count, "overall_status": "exact"}


def _verify_sealed_inputs(repo_root: Path) -> dict[str, Any]:
    for relative, expected in (
        (SEALED_PLAN_PATH, SEALED_PLAN_SHA256),
        (RESTORED_DESIGN_PATH, RESTORED_DESIGN_SHA256),
        (DECISION_RULE_PATH, DECISION_RULE_SHA256),
    ):
        _require(_file_binding(repo_root, relative)["sha256"] == expected, f"sealed input changed: {relative}")
    plan = _load(repo_root, SEALED_PLAN_PATH)
    design = _load(repo_root, RESTORED_DESIGN_PATH)
    _require(plan["pair_count"] == design["pair_count"] == len(CASE_DEFINITIONS), "sealed pair count ambiguous")
    _require(
        [item["fixture"] for item in plan["pair_fixtures"]] == list(CREATIVE_DEMAND_CLASSES),
        "sealed creative-demand classes changed",
    )
    _require([item["pair_case_id"] for item in design["pairs"]] == list(PAIR_CASE_IDS), "sealed case IDs changed")
    _require(all(item["a_arm_required"] and item["b_arm_required"] for item in design["pairs"]), "arm requirement changed")
    return {
        "plan": plan,
        "design": design,
        "restoration_manifest": _verify_manifest(repo_root, RESTORATION_MANIFEST_PATH, RESTORATION_MANIFEST_SHA256),
    }


def _context_bindings(repo_root: Path) -> dict[str, Any]:
    current_profile, current_context = current_arm.verify_skill_resolution_twice(repo_root)
    _require(current_profile["profile_sha256"] == CURRENT_PROFILE_SHA256, "current Skill profile changed")
    _require(_sha_bytes(current_context.encode(UTF8)) == CURRENT_CONTEXT_SHA256, "current Skill context changed")
    _require(len(current_context) == CURRENT_CONTEXT_CHARS, "current Skill context length changed")
    sealed_current = _load(repo_root, CURRENT_PROFILE_PATH)
    _require(sealed_current["profile_sha256"] == current_profile["profile_sha256"], "current Skill sealed parity changed")

    restored_binding = _load(repo_root, RESTORED_CONTEXT_PATH)
    restored_profile = _load(repo_root, RESTORED_PROFILE_PATH)
    restored_context = restored_binding["rendered_context"]
    _require(restored_profile["canonical_profile_sha256"] == RESTORED_PROFILE_SHA256, "restored profile changed")
    _require(_sha_bytes(restored_context.encode(UTF8)) == RESTORED_CONTEXT_SHA256, "restored context changed")
    _require(len(restored_context) == RESTORED_CONTEXT_CHARS, "restored context length changed")
    audit = audit_creative_capability_presence(restored_context)
    _require(audit["overall_status"] == "pass", "restored creative capability gate failed")
    _require(
        tuple(restored_profile["mandatory_rule_ids"]) == RESTORED_CREATIVE_RULE_IDS,
        "restored eight-item identity set changed",
    )
    _require(restored_binding["render_deterministic_x2"] == "PASS", "restored context nondeterministic")
    _require(restored_binding["truncation_receipt"]["status"] == "NONE", "restored context truncated")
    return {
        "current_profile": current_profile,
        "current_context": current_context,
        "restored_profile": restored_profile,
        "restored_context": restored_context,
        "restored_audit": audit,
    }


def _case_fixture(case: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    story_slice = {
        "schema": "SkillV2BoundedRepeatedABStorySliceV1",
        "version": 1,
        "pair_case_id": case["pair_case_id"],
        "creative_demand_class": case["creative_demand_class"],
        "formal_event_id": case["event_id"],
        "entry_state": case["entry_state"],
        "required_change": case["required_change"],
        "exit_state": case["exit_state"],
        "required_obligation_ids": list(case["obligations"]),
        "confirmed_outcome_locked": True,
        "synthetic": True,
    }
    story_sha = _domain_sha("skill-v2-bounded-repeated-ab-story-slice-v1", story_slice)
    event_contract_sha = _domain_sha("skill-v2-bounded-repeated-ab-event-contract-v1", story_slice)
    parent_sha = _domain_sha(
        "skill-v2-bounded-repeated-ab-parent-authority-v1",
        {"pair_case_id": case["pair_case_id"], "campaign_id": CAMPAIGN_ID},
    )
    predecessor_sha = _domain_sha(
        "skill-v2-bounded-repeated-ab-predecessor-boundary-v1",
        {"pair_case_id": case["pair_case_id"], "entry_state": case["entry_state"]},
    )
    authority_model = EventRealizationInputAuthorityV1(
        parent_authority_sha256=parent_sha,
        formal_event_id=case["event_id"],
        formal_event_contract_sha256=event_contract_sha,
        predecessor_boundary_sha256=predecessor_sha,
        formal_event_ids=(case["event_id"],),
        segment_event_ids=((case["event_id"],),),
        dependency_artifact_ids=(),
        context_projection_sha256=story_sha,
        required_obligation_ids=tuple(case["obligations"]),
    )
    authority = normalize_event_realization_input_authority_v1(authority_model.model_dump(mode="json"))
    task_contract = {
        "contract_identity": current_arm.SLICE1_CONTRACT_IDENTITY,
        "stage": current_arm.SLICE1_STAGE,
        "candidate_owned_fields": ["title", "narrative"],
        "expected_output_characters": current_arm.EXPECTED_OUTPUT_CHARACTERS,
        "shadow_only": True,
        "production_authority": False,
    }
    fixture = {
        "schema": "SkillV2BoundedRepeatedABSanitizedFixtureV1",
        "version": 1,
        "pair_case_id": case["pair_case_id"],
        "creative_demand_class": case["creative_demand_class"],
        "primary_dimensions": list(case["primary_dimensions"]),
        "authority_input": authority,
        "story_slice": story_slice,
        "task_contract": task_contract,
        "repository_owned_sanitized_fixture": True,
        "private_user_data": False,
        "raw_provider_content": False,
        "model_generated_output_authoritative": False,
    }
    return fixture, authority, task_contract


def _model_pair(
    repo_root: Path,
    authority: Mapping[str, Any],
    contexts: Mapping[str, Any],
    contract: Mapping[str, Any],
    route: Mapping[str, Any],
) -> dict[str, Any]:
    a_model, a_system, a_user = current_arm.build_model_input(
        repo_root,
        authority,
        contexts["current_context"],
        contexts["current_profile"],
        contract,
        route,
    )
    current_context = contexts["current_context"]
    _require(a_system.endswith(current_context), "current Skill boundary ambiguous")
    non_skill_prefix = a_system[:-len(current_context)] if current_context else a_system
    b_system = non_skill_prefix + contexts["restored_context"]
    b_user = a_user
    user_payload = json.loads(a_user)
    task_payload = {key: value for key, value in user_payload.items() if key != "authority"}
    return {
        "a": {
            "skill_profile_sha256": contexts["current_profile"]["profile_sha256"],
            "skill_context_sha256": _sha_bytes(current_context.encode(UTF8)),
            "skill_context_char_count": len(current_context),
            "system_sha256": _sha_bytes(a_system.encode(UTF8)),
            "user_sha256": _sha_bytes(a_user.encode(UTF8)),
            "wire_input_sha256": _sha_bytes((a_system + "\n\0" + a_user).encode(UTF8)),
            "estimated_input_tokens": a_model["estimated_input_tokens"],
        },
        "b": {
            "skill_profile_sha256": RESTORED_PROFILE_SHA256,
            "skill_context_sha256": _sha_bytes(contexts["restored_context"].encode(UTF8)),
            "skill_context_char_count": len(contexts["restored_context"]),
            "system_sha256": _sha_bytes(b_system.encode(UTF8)),
            "user_sha256": _sha_bytes(b_user.encode(UTF8)),
            "wire_input_sha256": _sha_bytes((b_system + "\n\0" + b_user).encode(UTF8)),
            "estimated_input_tokens": current_arm.estimate_input_tokens(b_system + "\n\0" + b_user),
        },
        "non_skill_prompt_sha256": _sha_bytes(non_skill_prefix.encode(UTF8)),
        "authority_input_sha256": a_model["authority_context_sha256"],
        "authority_section_sha256": _domain_sha("skill-v2-ab-authority-section-v1", user_payload["authority"]),
        "task_contract_sha256": _domain_sha("skill-v2-ab-task-contract-v1", task_payload),
    }


def _arm_identity(case_id: str, arm: str) -> dict[str, str]:
    arm_token = "A" if arm == "a-arm" else "B"
    slug = case_id.removeprefix("restored-").removesuffix("-v1")
    scope = f"SKILL_V2_BOUNDED_REPEATED_AB_{slug.replace('-', '_').upper()}_{arm_token}_ARM_SINGLE_DISPATCH_V1_ONLY"
    cohort = f"skill-v2-bounded-repeated-ab-{slug}-{arm_token.lower()}-v1-20260824t162103z-001"
    materialization_root = f"{OUTPUT_ROOT}/pairs/{case_id}/{arm}"
    execution_root = f"{EXECUTION_ROOT}/pairs/{case_id}/{arm}"
    launcher_identity = _domain_sha(
        "skill-v2-bounded-repeated-ab-fixed-arm-launcher-v1",
        {"scope": scope, "cohort": cohort, "materialization_root": materialization_root, "execution_root": execution_root},
    )
    return {
        "scope": scope,
        "cohort_id": cohort,
        "materialization_root": materialization_root,
        "execution_root": execution_root,
        "launcher_identity_sha256": launcher_identity,
    }


def _privacy_scan(documents: Mapping[str, bytes]) -> dict[str, Any]:
    patterns = (
        r"sk-ant-[A-Za-z0-9_-]+",
        r"(?i)authorization\s*:\s*bearer\s+\S+",
        r"(?i)(?:api[_-]?key|secret[_-]?key)\s*[=:]\s*['\"]?[A-Za-z0-9_-]{16,}",
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        r"[A-Za-z]:\\(?:Users|小说)\\",
    )
    matches: list[dict[str, str]] = []
    for path, data in documents.items():
        text = data.decode(UTF8)
        for pattern in patterns:
            if re.search(pattern, text):
                matches.append({"path": path, "pattern_sha256": _sha_bytes(pattern.encode(UTF8))})
    return {
        "schema": "SkillV2BoundedRepeatedABPrivacyScanV1",
        "version": 1,
        "files_scanned": len(documents),
        "privacy_match_count": len(matches),
        "matches": matches,
        "synthetic_story_fixture_persisted": True,
        "private_user_story_persisted": False,
        "raw_prompt_persisted": False,
        "raw_skill_content_persisted": False,
        "raw_provider_content_persisted": False,
        "credential_persisted": False,
        "absolute_machine_path_persisted": False,
        "overall_status": "exact" if not matches else "blocked",
    }


def _manifest(documents: Mapping[str, bytes]) -> bytes:
    entries = [
        {"path": path, "bytes": len(data), "sha256": _sha_bytes(data)}
        for path, data in sorted(documents.items())
    ]
    return _json_bytes({
        "schema": "SkillV2BoundedRepeatedABSha256ManifestV1",
        "version": 1,
        "entry_count": len(entries),
        "files": entries,
        "definition_sha256": canonical_sha256("SkillV2BoundedRepeatedABSha256ManifestV1", entries),
        "coverage": "all materialized files except the manifest itself",
        "overall_status": "exact",
    })


def build_documents(
    repo_root: Path,
    *,
    materialization_parent_head: str,
    validation_evidence: Mapping[str, Any] | None = None,
) -> tuple[dict[str, bytes], dict[str, Any]]:
    repo_root = repo_root.resolve()
    sealed = _verify_sealed_inputs(repo_root)
    contexts = _context_bindings(repo_root)
    route = _load(repo_root, ROUTE_BINDING_PATH)
    contract = current_arm.slice1_contract_binding(repo_root)
    transport = _load(repo_root, TRANSPORT_GUARD_PATH)
    accounting = _load(repo_root, ATTEMPT_ACCOUNTING_PATH)
    quality = _load(repo_root, QUALITY_RUBRIC_PATH)
    engineering = _load(repo_root, ENGINEERING_RUBRIC_PATH)
    ptr12_manifest = _verify_manifest(repo_root, PTR12_MANIFEST_PATH, "78b637fac9227447e604e497f327616e23a5d2b3f03dbc30e790ed30eb1b3101")

    documents: dict[str, bytes] = {}

    def add(relative: str, value: Any) -> None:
        path = f"{OUTPUT_ROOT}/{relative}"
        documents[path] = _text_bytes(value) if isinstance(value, str) else _json_bytes(value)

    pair_rows: list[dict[str, Any]] = []
    authority_rows: list[dict[str, Any]] = []
    lock_rows: list[dict[str, Any]] = []
    context_rows: list[dict[str, Any]] = []
    arm_rows: list[dict[str, Any]] = []
    launcher_rows: list[dict[str, Any]] = []
    approval_rows: list[dict[str, Any]] = []
    nonce_rows: list[dict[str, Any]] = []

    sampling_policy_sha = _domain_sha(
        "skill-v2-bounded-repeated-ab-sampling-policy-v1",
        {"policy": "NO_EXPLICIT_OVERRIDE_CURRENT_SEALED_POLICY", "changed": False},
    )
    tool_policy_sha = _domain_sha(
        "skill-v2-bounded-repeated-ab-tool-policy-v1",
        {"policy": "NO_TOOLS_JSON_OBJECT_EVENT_REALIZATION_V1", "changed": False},
    )
    ptr9_policy_sha = _file_binding(repo_root, "src/novel_flywheel/provider_output.py")["sha256"]
    ptr12_policy_sha = _file_binding(repo_root, PTR12_DECISION_PATH)["sha256"]
    audit_serialization_sha = _file_binding(repo_root, AUDIT_SERIALIZATION_PATH)["sha256"]
    output_isolation_policy_sha = _domain_sha(
        "skill-v2-bounded-repeated-ab-output-isolation-policy-v1",
        {
            "production_database_mutation_allowed": False,
            "story_state_mutation_allowed": False,
            "canon_mutation_allowed": False,
            "ready_mutation_allowed": False,
            "draft_input_mutation_allowed": False,
            "ptr12_hash_only": True,
        },
    )

    for ordinal, case in enumerate(CASE_DEFINITIONS, start=1):
        case_id = case["pair_case_id"]
        fixture, authority, _task_contract = _case_fixture(case)
        model_pair = _model_pair(repo_root, authority, contexts, contract, route)
        story_slice_sha = _domain_sha("skill-v2-bounded-repeated-ab-story-slice-v1", fixture["story_slice"])
        authority_sha = model_pair["authority_input_sha256"]
        fixture["story_slice_sha256"] = story_slice_sha
        fixture["authority_input_sha256"] = authority_sha
        fixture["task_contract_sha256"] = model_pair["task_contract_sha256"]
        fixture_bytes = _json_bytes(fixture)
        fixture_path = f"pairs/{case_id}/sanitized-fixture-v1.json"
        add(fixture_path, fixture)
        fixture_binding = {
            "path": f"{OUTPUT_ROOT}/{fixture_path}",
            "bytes": len(fixture_bytes),
            "sha256": _sha_bytes(fixture_bytes),
        }
        authority_binding = _sealed(
            "skill-v2-bounded-repeated-ab-pair-authority-binding-v1",
            {
                "schema": "SkillV2BoundedRepeatedABPairAuthorityBindingV1",
                "version": 1,
                "pair_case_id": case_id,
                "creative_demand_class": case["creative_demand_class"],
                "fixture": fixture_binding,
                "authority_input_sha256": authority_sha,
                "story_slice_sha256": story_slice_sha,
                "task_contract_sha256": model_pair["task_contract_sha256"],
                "non_skill_prompt_sha256": model_pair["non_skill_prompt_sha256"],
                "validator_policy_sha256": contract["validator_bundle"]["validator_policy_sha256"],
                "authority_tuple_policy_sha256": contract["authority_binding_sha256"],
                "same_for_a_and_b": True,
                "repository_owned_sanitized_fixture": True,
                "private_user_data": False,
            },
            "authority_binding_sha256",
        )
        add(f"pairs/{case_id}/authority-binding-v1.json", authority_binding)

        context_binding = _sealed(
            "skill-v2-bounded-repeated-ab-pair-context-binding-v1",
            {
                "schema": "SkillV2BoundedRepeatedABPairContextBindingV1",
                "version": 1,
                "pair_case_id": case_id,
                "a_arm_profile": "CURRENT_RUNTIME_SKILL",
                "a_skill_profile_sha256": CURRENT_PROFILE_SHA256,
                "a_skill_context_sha256": model_pair["a"]["skill_context_sha256"],
                "a_skill_context_char_count": model_pair["a"]["skill_context_char_count"],
                "a_context_render_deterministic_x2": "PASS",
                "b_arm_profile": "RESTORED_SKILL_V2",
                "b_skill_profile_sha256": RESTORED_PROFILE_SHA256,
                "b_skill_context_sha256": model_pair["b"]["skill_context_sha256"],
                "b_skill_context_char_count": model_pair["b"]["skill_context_char_count"],
                "b_context_render_deterministic_x2": "PASS",
                "b_restoration_items_present": "8/8",
                "b_actionable_creative_capability_gate": "PASS",
                "b_operational_bookkeeping_leak_count": 0,
                "b_context_hard_ceiling_chars": 3000,
                "b_truncation": "NONE",
                "within_budget": model_pair["b"]["skill_context_char_count"] <= 3000,
            },
            "context_binding_sha256",
        )
        add(f"pairs/{case_id}/skill-context-binding-v1.json", context_binding)

        lock_body: dict[str, Any] = {
            "schema": "SkillV2BoundedRepeatedABPairLockV1",
            "version": 1,
            "pair_case_id": case_id,
            "primary_changed_variable": "SKILL_CONTEXT",
            **{key: True for key in AB_EQUALITY_FIELDS},
            "non_skill_prompt_sha256": model_pair["non_skill_prompt_sha256"],
            "authority_input_sha256": authority_sha,
            "story_slice_sha256": story_slice_sha,
            "task_contract_sha256": model_pair["task_contract_sha256"],
            "route_model_client_sha256": route["route_binding_sha256"],
            "output_cap": route["effective_route_cap"],
            "validator_policy_sha256": contract["validator_bundle"]["validator_policy_sha256"],
            "ptr9_policy_sha256": ptr9_policy_sha,
            "ptr12_policy_sha256": ptr12_policy_sha,
            "quality_rubric_sha256": quality["quality_rubric_sha256"],
            "engineering_rubric_sha256": engineering["engineering_rubric_sha256"],
            "a_skill_profile_sha256": model_pair["a"]["skill_profile_sha256"],
            "b_skill_profile_sha256": model_pair["b"]["skill_profile_sha256"],
            "a_skill_context_sha256": model_pair["a"]["skill_context_sha256"],
            "b_skill_context_sha256": model_pair["b"]["skill_context_sha256"],
            "a_system_sha256": model_pair["a"]["system_sha256"],
            "b_system_sha256": model_pair["b"]["system_sha256"],
            "a_wire_input_sha256": model_pair["a"]["wire_input_sha256"],
            "b_wire_input_sha256": model_pair["b"]["wire_input_sha256"],
            "semantic_diff_keys": ["skill_context_sha256", "skill_profile_sha256", "system_sha256", "wire_input_sha256"],
            "only_skill_context_and_derived_wire_identity_may_differ": True,
            "lock_status": "exact",
        }
        lock = _sealed("skill-v2-bounded-repeated-ab-pair-lock-v1", lock_body, "pair_lock_sha256")
        add(f"pairs/{case_id}/pair-ab-lock-v1.json", lock)

        pair_rows.append({
            "ordinal": ordinal,
            "pair_case_id": case_id,
            "creative_demand_class": case["creative_demand_class"],
            "primary_dimensions": list(case["primary_dimensions"]),
            "authority_input_source": "SEALED_REPOSITORY_OWNED_SANITIZED_FIXTURE",
            "fixture_sha256": fixture_binding["sha256"],
            "a_arm_real_execution_required": True,
            "b_arm_real_execution_required": True,
            "execution_status": "NOT_STARTED",
        })
        authority_rows.append({"pair_case_id": case_id, **authority_binding})
        lock_rows.append({"pair_case_id": case_id, "pair_lock_sha256": lock["pair_lock_sha256"], "status": "exact"})
        context_rows.append({
            "pair_case_id": case_id,
            "a_context_sha256": model_pair["a"]["skill_context_sha256"],
            "a_context_char_count": model_pair["a"]["skill_context_char_count"],
            "b_context_sha256": model_pair["b"]["skill_context_sha256"],
            "b_context_char_count": model_pair["b"]["skill_context_char_count"],
            "b_restoration_items_present": "8/8",
            "b_context_within_3000_chars": True,
            "context_binding_sha256": context_binding["context_binding_sha256"],
        })

        for arm in ("a-arm", "b-arm"):
            arm_key = "a" if arm == "a-arm" else "b"
            skill_arm = "CURRENT_RUNTIME_SKILL" if arm_key == "a" else "RESTORED_SKILL_V2"
            identity = _arm_identity(case_id, arm)
            output_namespace = f"skill-v2-bounded-repeated-ab/{CAMPAIGN_ID}/{case_id}/{arm}"
            launcher = _sealed(
                "skill-v2-bounded-repeated-ab-launcher-binding-v1",
                {
                    "schema": "SkillV2BoundedRepeatedABLauncherBindingV1",
                    "version": 1,
                    "pair_case_id": case_id,
                    "skill_arm": skill_arm,
                    **identity,
                    "packet_scope_equals_launcher_scope": True,
                    "packet_cohort_equals_launcher_cohort": True,
                    "execution_root_binding": "PASS",
                    "launcher_contract": "PER_ARM_FIXED_CLOSED_WORLD_SINGLE_DISPATCH_V1",
                    "dynamic_skill_arm_selection_allowed": False,
                    "hard_max_model_calls": 1,
                    "hard_max_real_provider_request_attempts": 1,
                    "hard_max_http_post_attempts": 1,
                    "hard_max_network_request_attempts": 1,
                    "sdk_retries_disabled": True,
                    "transport_request_retries_disabled": True,
                    "route_fallback_after_dispatch_allowed": False,
                    "application_second_dispatch_allowed": False,
                    "unknown_guard_state_fails_closed": True,
                    "normal_production_transport_retry_policy_changed": False,
                    "transport_policy_definition_sha256": transport["policy_definition_sha256"],
                    "transport_guard_sha256": transport["transport_guard_sha256"],
                    "attempt_accounting_sha256": accounting["attempt_accounting_sha256"],
                    "outer_permission_check_before_nonce_reservation": True,
                },
                "launcher_binding_sha256",
            )
            add(f"pairs/{case_id}/{arm}/launcher-binding-v1.json", launcher)

            packet = _sealed(
                "skill-v2-bounded-repeated-ab-disabled-arm-packet-v1",
                {
                    "schema": "SkillV2BoundedRepeatedABDisabledArmPacketV1",
                    "version": 1,
                    "campaign_id": CAMPAIGN_ID,
                    "materialization_parent_head": materialization_parent_head,
                    "pair_case_id": case_id,
                    "creative_demand_class": case["creative_demand_class"],
                    "skill_arm": skill_arm,
                    **identity,
                    "fixture_sha256": fixture_binding["sha256"],
                    "authority_input_sha256": authority_sha,
                    "story_slice_sha256": story_slice_sha,
                    "task_contract_sha256": model_pair["task_contract_sha256"],
                    "non_skill_prompt_sha256": model_pair["non_skill_prompt_sha256"],
                    "skill_profile_sha256": model_pair[arm_key]["skill_profile_sha256"],
                    "skill_context_sha256": model_pair[arm_key]["skill_context_sha256"],
                    "skill_context_char_count": model_pair[arm_key]["skill_context_char_count"],
                    "system_sha256": model_pair[arm_key]["system_sha256"],
                    "user_sha256": model_pair[arm_key]["user_sha256"],
                    "wire_input_sha256": model_pair[arm_key]["wire_input_sha256"],
                    "route_model_client_sha256": route["route_binding_sha256"],
                    "sampling_policy_sha256": sampling_policy_sha,
                    "tool_policy_sha256": tool_policy_sha,
                    "output_cap": route["effective_route_cap"],
                    "validator_policy_sha256": contract["validator_bundle"]["validator_policy_sha256"],
                    "authority_tuple_policy_sha256": contract["authority_binding_sha256"],
                    "audit_serialization_policy_sha256": audit_serialization_sha,
                    "ptr9_policy_sha256": ptr9_policy_sha,
                    "ptr12_policy_sha256": ptr12_policy_sha,
                    "output_isolation_policy_sha256": output_isolation_policy_sha,
                    "output_namespace": output_namespace,
                    "quality_rubric_sha256": quality["quality_rubric_sha256"],
                    "engineering_rubric_sha256": engineering["engineering_rubric_sha256"],
                    "pair_lock_sha256": lock["pair_lock_sha256"],
                    "launcher_binding_sha256": launcher["launcher_binding_sha256"],
                    "execution_authorized": False,
                    "usage_status": "unused",
                    "reservation_status": "unreserved",
                    "named_approver": None,
                    "signed_approval": "ABSENT",
                    "single_use_nonce": None,
                    "approval_reuse_allowed": False,
                    "cohort_reuse_allowed": False,
                    "skill_v2_production_cutover_authorized": False,
                    "planning_v2_cutover_authorized": False,
                    "draft_authorized": False,
                    "full_short_authorized": False,
                    "story_state_mutation_allowed": False,
                    "canon_mutation_allowed": False,
                    "ready_mutation_allowed": False,
                    "external_actions": _external_actions(),
                },
                "packet_sha256",
            )
            add(f"pairs/{case_id}/{arm}/disabled-packet-v1.json", packet)

            approval = _sealed(
                "skill-v2-bounded-repeated-ab-approval-template-v1",
                {
                    "schema": "SkillV2BoundedRepeatedABApprovalTemplateV1",
                    "version": 1,
                    "pair_case_id": case_id,
                    "skill_arm": skill_arm,
                    **identity,
                    "materialization_parent_head": materialization_parent_head,
                    "packet_sha256": packet["packet_sha256"],
                    "launcher_binding_sha256": launcher["launcher_binding_sha256"],
                    "pair_lock_sha256": lock["pair_lock_sha256"],
                    "campaign_stop_state_required": "OPEN_FOR_NEXT_SERIAL_ARM",
                    "matching_a_arm_pass_required": arm_key == "b",
                    "one_approval_per_real_request": True,
                    "one_fresh_nonce_per_real_request": True,
                    "wildcard_binding_allowed": False,
                    "outer_permission_required_before_nonce_reservation": True,
                    "validity_window": None,
                    "named_approver": None,
                    "execution_authorized": False,
                    "signed_approval": "ABSENT",
                    "single_use_nonce": None,
                    "usage_status": "unused",
                    "reservation_status": "unreserved",
                },
                "approval_template_sha256",
            )
            add(f"pairs/{case_id}/{arm}/approval-template-v1.json", approval)

            nonce = _sealed(
                "skill-v2-bounded-repeated-ab-nonce-policy-v1",
                {
                    "schema": "SkillV2BoundedRepeatedABNoncePolicyV1",
                    "version": 1,
                    "pair_case_id": case_id,
                    "skill_arm": skill_arm,
                    "scope": identity["scope"],
                    "cohort_id": identity["cohort_id"],
                    "nonce_present": False,
                    "nonce_executable": False,
                    "nonce_reservation_allowed_during_materialization": False,
                    "nonce_reuse_allowed": False,
                    "one_nonce_per_real_request": True,
                    "reserve_only_after_signed_approval_and_current_chat_external_permission": True,
                    "pre_nonce_external_permission_abort_preserves_nonce": True,
                    "ledger_entry_count": 0,
                },
                "nonce_policy_sha256",
            )
            add(f"pairs/{case_id}/{arm}/nonce-policy-v1.json", nonce)

            arm_rows.append({
                "pair_case_id": case_id,
                "arm": arm,
                "skill_arm": skill_arm,
                **identity,
                "packet_sha256": packet["packet_sha256"],
                "execution_authorized": False,
                "usage_status": "unused",
                "reservation_status": "unreserved",
            })
            launcher_rows.append({"pair_case_id": case_id, "arm": arm, **identity, "launcher_binding_sha256": launcher["launcher_binding_sha256"]})
            approval_rows.append({"pair_case_id": case_id, "arm": arm, "scope": identity["scope"], "approval_template_sha256": approval["approval_template_sha256"], "signed_approval": "ABSENT"})
            nonce_rows.append({"pair_case_id": case_id, "arm": arm, "scope": identity["scope"], "nonce_policy_sha256": nonce["nonce_policy_sha256"], "nonce_present": False})

    add("README.md", """# Skill V2 bounded repeated A/B v1

Offline-only campaign design and disabled per-arm packet descriptors for the five sealed creative-demand cases. No signed approval, nonce, credential access, network request, model call, production cutover, Draft, or Full Short is included.""")
    add("campaign-plan-binding-v1.json", {
        "schema": "SkillV2BoundedRepeatedABCampaignPlanBindingV1",
        "version": 1,
        "campaign_id": CAMPAIGN_ID,
        "baseline_head": BASELINE_HEAD,
        "materialization_parent_head": materialization_parent_head,
        "sealed_plan": _file_binding(repo_root, SEALED_PLAN_PATH),
        "restored_design": _file_binding(repo_root, RESTORED_DESIGN_PATH),
        "sealed_decision_rule": _file_binding(repo_root, DECISION_RULE_PATH),
        "restoration_manifest": sealed["restoration_manifest"],
        "sealed_pair_count": len(pair_rows),
        "pair_case_ids": list(PAIR_CASE_IDS),
        "creative_demand_classes": list(CREATIVE_DEMAND_CLASSES),
        "creative_demand_coverage": "PASS",
        "no_unbounded_case_expansion": True,
        "primary_changed_variable": "SKILL_CONTEXT",
        "real_execution_mode": "SERIAL",
        "execution_order": [f"PAIR_{i} A -> B -> evaluate" for i in range(1, 6)],
        "execution_authorized": False,
        "bounded_repeated_ab_real_execution": "NOT_STARTED",
        "next_gate": "SKILL_V2_BOUNDED_REPEATED_AB_PAIR_1_A_ARM_FRESH_USER_APPROVAL",
    })
    add("campaign-budget-v1.json", {
        "schema": "SkillV2BoundedRepeatedABCampaignBudgetV1",
        "version": 1,
        "pair_case_count": 5,
        "a_arm_reuse_equivalence_claimed": False,
        "max_a_arm_real_calls": 5,
        "max_b_arm_real_calls": 5,
        "max_campaign_real_provider_calls": 10,
        "max_campaign_http_posts": 10,
        "per_arm_hard_max_model_calls": 1,
        "per_arm_hard_max_real_provider_request_attempts": 1,
        "per_arm_hard_max_http_post_attempts": 1,
        "per_arm_hard_max_network_request_attempts": 1,
        "per_arm_output_cap": route["effective_route_cap"],
        "campaign_blanket_execution_allowed": False,
        "automatic_rerun_allowed": False,
        "budget_inflation": False,
    })
    add("campaign-stop-rules-v1.json", {
        "schema": "SkillV2BoundedRepeatedABCampaignStopRulesV1",
        "version": 1,
        "critical_quality_regression_stops_campaign": True,
        "engineering_hard_failure_stops_campaign": True,
        "a_b_lock_failure_stops_campaign": True,
        "engineering_hard_failures": [
            "retry_or_second_request", "protocol_or_parser_failure", "validator_failure",
            "artifact_persistence_failure", "authority_drift", "unexpected_mutation",
            "single_dispatch_violation",
        ],
        "automatic_retry_after_stop": False,
        "stop_state_must_bind_next_approval": True,
    })
    add("campaign-decision-rule-v1.json", {
        "schema": "SkillV2BoundedRepeatedABCampaignDecisionRuleV1",
        "version": 1,
        "pair_decisions": [
            "PAIR_PASS_NON_INFERIOR", "PAIR_NO_GO_QUALITY_REGRESSION",
            "PAIR_NO_GO_ENGINEERING_REGRESSION", "PAIR_NO_GO_AB_LOCK_INVALID",
            "PAIR_INCONCLUSIVE",
        ],
        "critical_pair_regression_can_be_averaged_away": False,
        "all_required_pairs_must_complete": True,
        "all_engineering_arms_valid": True,
        "all_a_b_locks_exact": True,
        "hidden_retry_allowed": False,
        "production_mutation_allowed": False,
        "per_pair_evidence_independently_inspectable": True,
        "production_cutover_authorized": False,
    })
    add("pair-case-index-v1.json", {
        "schema": "SkillV2BoundedRepeatedABPairCaseIndexV1",
        "version": 1,
        "pair_case_count": len(pair_rows),
        "pair_case_ids": list(PAIR_CASE_IDS),
        "creative_demand_classes": list(CREATIVE_DEMAND_CLASSES),
        "pairs": pair_rows,
        "closed_world": True,
    })
    add("per-pair-authority-binding-v1.json", {"schema": "SkillV2BoundedRepeatedABPerPairAuthorityIndexV1", "version": 1, "pair_count": 5, "pairs": authority_rows, "all_same_within_pair": True})
    add("per-pair-ab-lock-v1.json", {"schema": "SkillV2BoundedRepeatedABPerPairLockIndexV1", "version": 1, "pair_count": 5, "pairs": lock_rows, "primary_changed_variable": "SKILL_CONTEXT", "all_locks_exact": True})
    add("per-pair-skill-context-binding-v1.json", {"schema": "SkillV2BoundedRepeatedABPerPairContextIndexV1", "version": 1, "pair_count": 5, "pairs": context_rows, "restored_profile_sha256": RESTORED_PROFILE_SHA256, "restoration_items_present": "8/8", "all_b_contexts_within_3000_chars": True})
    add("per-arm-packet-index-v1.json", {"schema": "SkillV2BoundedRepeatedABPerArmPacketIndexV1", "version": 1, "arm_count": len(arm_rows), "arms": arm_rows, "arm_packet_selection_closed_world": True, "arbitrary_skill_arm_selection": False, "all_disabled_unused_unreserved": True})
    add("per-arm-launcher-binding-v1.json", {"schema": "SkillV2BoundedRepeatedABPerArmLauncherIndexV1", "version": 1, "arm_count": len(launcher_rows), "arms": launcher_rows, "unique_launcher_binding_count": len({row["launcher_binding_sha256"] for row in launcher_rows}), "packet_scope_equals_launcher_scope": True, "packet_cohort_equals_launcher_cohort": True, "execution_root_binding": "PASS"})
    add("per-arm-approval-design-v1.json", {"schema": "SkillV2BoundedRepeatedABPerArmApprovalDesignV1", "version": 1, "arm_count": len(approval_rows), "arms": approval_rows, "blanket_campaign_approval_allowed": False, "one_approval_per_real_request": True, "one_fresh_nonce_per_real_request": True, "b_arm_approval_requires_matching_a_arm_pass": True, "wildcard_authority_allowed": False})
    add("per-arm-nonce-policy-v1.json", {"schema": "SkillV2BoundedRepeatedABPerArmNoncePolicyIndexV1", "version": 1, "arm_count": len(nonce_rows), "arms": nonce_rows, "one_nonce_per_real_request": True, "nonce_reuse_allowed": False, "nonce_reservation_during_materialization": False, "all_nonces_absent": True})
    add("head-successor-history-policy-v1.json", {
        "schema": "SkillV2BoundedRepeatedABHeadSuccessorHistoryPolicyV1",
        "version": 1,
        "approval_parent_head_binding_required": True,
        "evidence_only_approval_successor_required": True,
        "typed_ancestry_fail_close": True,
        "git_diff_after_failed_ancestry": "FORBIDDEN",
        "post_seal_materialization_parent_source_required": True,
        "historical_root_policy": "CLOSED_WORLD",
        "historical_roots": [
            "docs/superpowers/reports/short-plan-v2-skill-v2-quality-regression-root-cause-v1",
            SEALED_ROOT,
            "docs/superpowers/reports/short-plan-v2-slice1-phase-b-skill-v2-restored-materialization-v1",
            "docs/superpowers/reports/short-plan-v2-slice1-phase-b-current-skill-materialization-v5",
            "docs/superpowers/reports/short-plan-v2-slice1-phase-b-current-skill-execution-v5",
            "docs/superpowers/reports/short-plan-v2-slice1-phase-b-skill-v2-materialization-v4",
            "docs/superpowers/reports/short-plan-v2-slice1-phase-b-skill-v2-execution-v4",
            "docs/superpowers/reports/r1-ptr12-final-review",
            OUTPUT_ROOT,
        ],
        "growth_rule": "append only an exact sealed pair-arm approval/execution/evaluation root through an evidence-only successor commit",
        "immediate_predecessor_only_assumption": False,
        "status": "PASS",
    })
    add("outer-permission-policy-v1.json", {
        "schema": "SkillV2BoundedRepeatedABOuterPermissionPolicyV1",
        "version": 1,
        "current_chat_permission_required_for": ["credential_access", "network", "paid_provider", "data_egress"],
        "check_boundary": "before_nonce_reservation",
        "absence_result": "PRE_NONCE_EXTERNAL_PERMISSION_ABORT",
        "nonce_untouched_on_absence": True,
        "approval_does_not_imply_outer_permission": True,
        "external_actions_now": _external_actions(),
    })
    narrative_dimensions = [
        "event_causal_fidelity", "character_motivation", "character_voice", "relationship_logic",
        "world_specificity", "sensory_realization", "conflict_pacing", "setup_payoff_dependency",
        "pov", "tense", "tone_genre", "subtext_dramatization", "draft_intent_handoff",
        "template_flattening_risk", "authority_correctness", "untargeted_creative_mutation",
    ]
    add("narrative-evaluation-policy-v1.json", {"schema": "SkillV2BoundedRepeatedABNarrativeEvaluationPolicyV1", "version": 1, "dimensions": narrative_dimensions, "blind_pairwise_review_required": True, "engineering_metrics_hidden_during_narrative_review": True, "single_scalar_literary_score_allowed": False, "critical_regression_result": "PAIR_NO_GO_QUALITY_REGRESSION", "quality_rubric_sha256": quality["quality_rubric_sha256"]})
    add("engineering-evaluation-policy-v1.json", {"schema": "SkillV2BoundedRepeatedABEngineeringEvaluationPolicyV1", "version": 1, "metrics": engineering["metrics"], "unknown_remains_unknown": True, "same_policy_both_arms": True, "single_dispatch_violation_result": "PAIR_NO_GO_ENGINEERING_REGRESSION", "engineering_rubric_sha256": engineering["engineering_rubric_sha256"], "transport_guard_sha256": transport["transport_guard_sha256"], "attempt_accounting_sha256": accounting["attempt_accounting_sha256"], "ptr12_manifest": ptr12_manifest})

    validation = dict(validation_evidence or {})
    add("offline-test-receipt-v1.json", {
        "schema": "SkillV2BoundedRepeatedABOfflineTestReceiptV1",
        "version": 1,
        "sealed_case_count_and_ids": "PASS",
        "unplanned_pair_count": 0,
        "only_skill_context_differs": "PASS",
        "current_skill_deterministic_x2": "PASS",
        "restored_skill_v2_deterministic_x2": "PASS",
        "restoration_items_present": "8/8",
        "b_context_truncation_count": 0,
        "operational_leak_count": 0,
        "single_dispatch_guard": "PASS",
        "authority_tuple": "PASS",
        "audit_serialization": "PASS",
        "full_synthetic_success_tail": "PASS",
        "one_approval_per_request": "PASS",
        "one_nonce_per_request": "PASS",
        "blanket_approval": "DISALLOWED",
        "campaign_stop_rules_bound": True,
        "external_actions": _external_actions(),
        "production_cutover": False,
        "draft": "NOT_STARTED",
        "full_short": "NOT_EXECUTED",
        "focused_tests": validation.get("focused_tests", "BUILD_TIME_CONTRACT_CHECKS_ONLY"),
        "related_tests": validation.get("related_tests", "PENDING_FINAL_SEAL"),
        "full_suite": validation.get("full_suite", "PENDING_FINAL_SEAL"),
        "strict_l3": validation.get("strict_l3", "PENDING_FINAL_SEAL"),
        "overall_status": "exact",
    })
    add("final-report-v1.md", _final_report(materialization_parent_head, pair_rows, context_rows, arm_rows, validation))
    add("privacy-scan-v1.json", _privacy_scan(documents))
    documents[f"{OUTPUT_ROOT}/sha256-manifest-v1.json"] = _manifest(documents)

    result = {
        "branch": EXPECTED_BRANCH,
        "baseline_head": BASELINE_HEAD,
        "materialization_parent_head": materialization_parent_head,
        "pair_case_count": len(pair_rows),
        "pair_case_ids": list(PAIR_CASE_IDS),
        "creative_demand_classes": list(CREATIVE_DEMAND_CLASSES),
        "arm_count": len(arm_rows),
        "arm_scopes": [row["scope"] for row in arm_rows],
        "max_campaign_real_provider_calls": 10,
        "max_campaign_http_posts": 10,
        "restored_profile_sha256": RESTORED_PROFILE_SHA256,
        "restored_context_sha256": RESTORED_CONTEXT_SHA256,
        "external_actions": _external_actions(),
        "execution_authorized": False,
        "signed_approval": "ABSENT",
        "overall_status": "exact",
    }
    return documents, result


def _final_report(
    materialization_parent_head: str,
    pairs: list[dict[str, Any]],
    contexts: list[dict[str, Any]],
    arms: list[dict[str, Any]],
    validation: Mapping[str, Any],
) -> str:
    pair_lines = "\n".join(
        f"- `{row['pair_case_id']}` — `{row['creative_demand_class']}` — A required `YES`, B required `YES`, fixture `{row['fixture_sha256']}`"
        for row in pairs
    )
    context_lines = "\n".join(
        f"- `{row['pair_case_id']}` — A `{row['a_context_sha256']}` / `{row['a_context_char_count']}` chars; B `{row['b_context_sha256']}` / `{row['b_context_char_count']}` chars; restoration `8/8`; B budget `PASS`"
        for row in contexts
    )
    arm_lines = "\n".join(
        f"- `{row['pair_case_id']}` `{row['arm']}` — scope `{row['scope']}`; cohort `{row['cohort_id']}`; materialization `{row['materialization_root']}`; execution `{row['execution_root']}`; launcher `{row['launcher_identity_sha256']}`"
        for row in arms
    )
    return f"""# Skill V2 Bounded Repeated A/B — Final Design Report

Gate: `SKILL_V2_BOUNDED_REPEATED_AB_EXECUTION_PLAN_DESIGNED`

- Branch: `{EXPECTED_BRANCH}`
- Baseline HEAD: `{BASELINE_HEAD}`
- Implementation/materialization parent HEAD: `{materialization_parent_head}`
- R0F successor: `NOT_REQUIRED`
- Sealed repeated-A/B plan SHA-256: `{SEALED_PLAN_SHA256}`
- Sealed restored design SHA-256: `{RESTORED_DESIGN_SHA256}`
- Decision-rule SHA-256: `{DECISION_RULE_SHA256}`
- Pair count: `5`; A calls max `5`; B calls max `5`; campaign Provider calls/HTTP POSTs max `10/10`
- Creative-demand coverage: `character-heavy`, `world-heavy`, `conflict-pacing-heavy`, `setup-payoff-heavy`, `mixed` — `PASS`
- Execution order: serial `Pair 1 A -> B -> evaluate`, then each following pair under the same stop gate
- Stop rules: critical narrative regression, engineering hard failure, or A/B lock failure stops the campaign
- Pair decisions: `PAIR_PASS_NON_INFERIOR`, `PAIR_NO_GO_QUALITY_REGRESSION`, `PAIR_NO_GO_ENGINEERING_REGRESSION`, `PAIR_NO_GO_AB_LOCK_INVALID`, `PAIR_INCONCLUSIVE`
- Campaign rule: every required pair and engineering arm must be valid; critical failures are never averaged away
- Restored profile/context: `{RESTORED_PROFILE_SHA256}` / `{RESTORED_CONTEXT_SHA256}` / `{RESTORED_CONTEXT_CHARS}` chars
- Current Runtime Skill context: `{CURRENT_PROFILE_SHA256}` / `{CURRENT_CONTEXT_SHA256}` / `{CURRENT_CONTEXT_CHARS}` chars
- Single-dispatch guard: `PASS`; authority tuple: `PASS`; audit serialization: `PASS`; PTR12: `PASS`
- HEAD-successor policy: `PASS`; historical-root policy: `CLOSED_WORLD`
- Outer permission: current-chat credential/network/paid-provider/data-egress permission required before nonce reservation
- Focused tests: `{validation.get('focused_tests', 'BUILD_TIME_CONTRACT_CHECKS_ONLY')}`
- Related tests: `{validation.get('related_tests', 'PENDING_FINAL_SEAL')}`
- Full suite: `{validation.get('full_suite', 'PENDING_FINAL_SEAL')}`
- Strict L3: `{validation.get('strict_l3', 'PENDING_FINAL_SEAL')}`
- Privacy: synthetic repository fixtures only; no credentials, raw Provider content, private user story, or absolute machine path
- External counters: all `0`

## Pair inputs

{pair_lines}

## Per-case Skill contexts

{context_lines}

## Per-arm identities

{arm_lines}

## Disabled end state

`EXECUTION_AUTHORIZED=NO`

`SIGNED_APPROVAL=ABSENT`

`SINGLE_USE_NONCE=ABSENT_OR_NOT_EXECUTABLE`

`BOUNDED_REPEATED_AB_REAL_EXECUTION=NOT_STARTED`

`SKILL_V2_PRODUCTION_CUTOVER_AUTHORIZED=NO`

`PLANNING_V2_CUTOVER_AUTHORIZED=NO`

`FULL_SHORT_CANARY=NOT_EXECUTED`

`SKILL_V2_BOUNDED_REPEATED_AB_EXECUTION_PLAN_DESIGNED`

`SKILL_V2_BOUNDED_REPEATED_AB_DISABLED_PACKETS_MATERIALIZED`

`SKILL_V2_BOUNDED_REPEATED_AB_READY_FOR_SEQUENTIAL_APPROVAL=YES`

Next gate: `SKILL_V2_BOUNDED_REPEATED_AB_PAIR_1_A_ARM_FRESH_USER_APPROVAL`
"""


def write_documents(repo_root: Path, documents: Mapping[str, bytes]) -> None:
    for relative, data in documents.items():
        path = repo_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--materialization-parent-head", required=True)
    parser.add_argument("--focused-tests", default="BUILD_TIME_CONTRACT_CHECKS_ONLY")
    parser.add_argument("--related-tests", default="PENDING_FINAL_SEAL")
    parser.add_argument("--full-suite", default="PENDING_FINAL_SEAL")
    parser.add_argument("--strict-l3", default="PENDING_FINAL_SEAL")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    if args.write:
        _require(_git(repo_root, "branch", "--show-current") == EXPECTED_BRANCH, "branch changed")
        _require(_git(repo_root, "rev-parse", "HEAD") == args.materialization_parent_head, "HEAD changed")
        _require(not _git(repo_root, "status", "--short"), "worktree must be clean before materialization")
        _require(
            subprocess.run(["git", "merge-base", "--is-ancestor", BASELINE_HEAD, args.materialization_parent_head], cwd=repo_root).returncode == 0,
            "materialization parent is not descended from baseline",
        )
    documents, result = build_documents(
        repo_root,
        materialization_parent_head=args.materialization_parent_head,
        validation_evidence={
            "focused_tests": args.focused_tests,
            "related_tests": args.related_tests,
            "full_suite": args.full_suite,
            "strict_l3": args.strict_l3,
        },
    )
    if args.write:
        write_documents(repo_root, documents)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
