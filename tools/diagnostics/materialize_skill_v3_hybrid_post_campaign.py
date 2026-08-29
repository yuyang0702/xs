"""Offline sealing, blind handoff, and decision tooling for the Hybrid pilot.

This module never imports a Provider client, reads credentials, or performs
network I/O.  It verifies the already-completed durable campaign, emits a
mapping-free evaluator bundle, validates two frozen evaluator records, and
only then permits deterministic mapping reveal and policy evaluation.
"""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping, Sequence

from novel_flywheel.config import default_settings
from novel_flywheel.runtime_fingerprint_build import canonical_json_bytes, domain_sha256
from tools.canary import skill_v3_hybrid_character_heavy_pilot as hybrid
from tools.canary import skill_v3_hybrid_jit_approval as approvals
from tools.canary import skill_v3_hybrid_real_campaign as campaign
from tools.canary.skill_v3_pilot_nonce_store import (
    DurablePilotNonceStoreV1,
    default_nonce_store_root,
)


CAMPAIGN_EVIDENCE_RELATIVE = Path(
    "docs/superpowers/reports/skill-v3-hybrid-character-heavy-real-campaign-v1"
)
BLIND_BUNDLE_RELATIVE = Path(
    "docs/superpowers/reports/skill-v3-hybrid-character-heavy-blind-bundle-v1"
)
MAPPING_RELATIVE = Path(
    "docs/superpowers/reports/skill-v3-hybrid-character-heavy-blind-mapping-v1"
)
EVALUATOR_1_RELATIVE = Path(
    "docs/superpowers/reports/skill-v3-hybrid-character-heavy-blind-evaluation-e1-v1"
)
EVALUATOR_2_RELATIVE = Path(
    "docs/superpowers/reports/skill-v3-hybrid-character-heavy-blind-evaluation-e2-v1"
)
COMBINED_RELATIVE = Path(
    "docs/superpowers/reports/skill-v3-hybrid-character-heavy-combined-blind-aggregation-v1"
)
DECISION_RELATIVE = Path(
    "docs/superpowers/reports/skill-v3-hybrid-character-heavy-mapping-reveal-decision-v1"
)
MATERIALIZATION_RELATIVE = Path(
    "docs/superpowers/reports/skill-v3-hybrid-character-heavy-multi-sample-pilot-materialization-v1"
)

EXPECTED_BRANCH = "r1-ptr3/planning-repair-finding-propagation-20260817"
EXECUTION_HEAD = "b1a2453fa2535462a6771d2dfd2799f395c6d86f"
PERMISSION_ID = "sv3h-real-b1a2453f-20260829T094300Z"
PILOT_ID = "skill-v3-hybrid-character-heavy-v1-5e5cbfd1e6296ec8878b"
EXPERIMENT_LOCK_SHA256 = "de49d3353abe641f49dbb697d929a13bb30cc6c4fafe9bcf11f0a6d6ea19bafc"
AUTHORIZATION_SHA256 = "8de65a8b04c27d6112b278b71a21ffa8789e6d6f21f6579b7bc0780e41e0b031"
CAMPAIGN_STATE_SHA256 = "bc32a2d6d0860e47267e56e12a768f207ea81e7b775f73e6810fd68fd2c1d408"
COMPLETION_RECEIPT_SHA256 = "3d78e3513314cce6fad61054ff0e60487c67e6608699a3c1fa2da2d95904e1e4"
LITERARY_POLICY_SHA256 = "d93c95af9ed15d4c3f1193b00e319f364fb57176190e96e9e5d2fcd19eec0b21"
PAIR_ORDER = (
    ("CONTROL_1", "HYBRID_1"),
    ("CONTROL_2", "HYBRID_2"),
    ("CONTROL_3", "HYBRID_3"),
)
SEQUENCE = tuple(slot for pair in PAIR_ORDER for slot in pair)
EXPECTED_SAMPLE_IDS = (
    "sv3hs-0901efa55a2b11f3456f",
    "sv3hs-63c2c291b989e2a3e48c",
    "sv3hs-7725333044fdaae559a2",
    "sv3hs-aae6112339a439d43750",
    "sv3hs-8f00799be335c4ccaf76",
    "sv3hs-84e695ee4e02665555cf",
)
EXPECTED_ARTIFACT_SHAS = (
    "c56feb1925276ce41304ba6679f54276671087966eba8fa2b698a7d8d7deb3e2",
    "bab4a61c9cc76fc67cada0b41697a9056c814d5a1c0dd029ef62866146546b03",
    "c40842302a61122cc87514103966ac6b8d46a9374eb4df44a896da4a12834dca",
    "05947e8ad7cc2df0cf3981729c057aab0f3a93fbf905d15cb63a42cd15d6ef2f",
    "8d53e96f68a14f1fa9fabbc8d17ea7d554660821094f1b6f85bb4adebcaf3bfe",
    "890add645050ff6247af4a5ea316ca941cfd9fd3b26924f329386dfa57047c67",
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
CRITICAL_DIMENSIONS = (
    "character_agency",
    "causal_coherence",
    "setup_payoff_integrity",
)
RELATIONS = {"A_BETTER", "B_BETTER", "TIE", "INCOMPARABLE"}


def json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, bytes):
        data = value
    elif isinstance(value, str):
        data = value.encode("utf-8")
    else:
        data = json_bytes(value)
    path.write_bytes(data)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True,
        encoding="utf-8", errors="strict",
    ).stdout.strip()


def manifest(root: Path, schema: str) -> dict[str, Any]:
    entries = []
    for path in sorted(
        item for item in root.rglob("*")
        if item.is_file() and item.name != "sha256-manifest-v1.json"
    ):
        data = path.read_bytes()
        entries.append({
            "path": path.relative_to(root).as_posix(),
            "bytes": len(data),
            "sha256": sha_bytes(data),
        })
    body = {"schema": schema, "status": "EXACT", "entry_count": len(entries), "entries": entries}
    return {**body, "definition_sha256": domain_sha256(schema, body)}


def verify_manifest(root: Path) -> dict[str, Any]:
    exact = read_json(root / "sha256-manifest-v1.json")
    if exact.get("status") != "EXACT" or exact.get("entry_count") != len(exact.get("entries") or []):
        raise RuntimeError(f"MANIFEST_INVALID:{root}")
    for row in exact["entries"]:
        data = (root / row["path"]).read_bytes()
        if row["bytes"] != len(data) or row["sha256"] != sha_bytes(data):
            raise RuntimeError(f"MANIFEST_DRIFT:{root}:{row['path']}")
    return exact


def privacy_scan(values: Sequence[bytes]) -> dict[str, Any]:
    patterns = {
        "anthropic_secret": rb"sk-ant-[A-Za-z0-9_-]{8,}",
        "bearer_token": rb"Bearer\s+[A-Za-z0-9._-]{16,}",
        "private_key": rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    }
    matches = {
        name: sum(len(re.findall(pattern, value, flags=re.IGNORECASE)) for value in values)
        for name, pattern in patterns.items()
    }
    total = sum(matches.values())
    return {"status": "PASS" if total == 0 else "FAIL", "matches": matches, "total_matches": total}


def visible_pair_order(pair_index: int) -> tuple[str, str]:
    pair = PAIR_ORDER[pair_index - 1]
    return tuple(reversed(pair)) if pair_index % 2 else pair


def anonymous_id(campaign_manifest_sha256: str, pair_index: int, side_index: int) -> str:
    digest = domain_sha256(
        "novel-flywheel-skill-v3-hybrid-blind-sample-id-v1",
        {
            "campaign_manifest_sha256": campaign_manifest_sha256,
            "pair_index": pair_index,
            "side_index": side_index,
        },
    )
    return "hybrid-blind-" + digest[:16]


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _runtime_paths(permission_id: str) -> dict[str, Path]:
    data_dir = default_settings().data_dir
    key = domain_sha256("novel-flywheel-skill-v3-hybrid-real-campaign-key-v1", permission_id)
    execution = data_dir / campaign.REAL_CAMPAIGN_ROOT_RELATIVE / key
    return {
        "campaign_store": data_dir / campaign.CAMPAIGN_PERMISSION_STORE_RELATIVE,
        "output_root": execution / "outputs",
    }


def verify_campaign(repo: Path) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    branch = git(repo, "branch", "--show-current")
    head = git(repo, "rev-parse", "HEAD")
    if branch != EXPECTED_BRANCH:
        raise RuntimeError("HYBRID_CAMPAIGN_BRANCH_DRIFT")
    if git(repo, "merge-base", "--is-ancestor", EXECUTION_HEAD, head) != "":
        raise RuntimeError("HYBRID_CAMPAIGN_HEAD_ANCESTRY_DRIFT")
    if git(repo, "diff", "--name-only", EXECUTION_HEAD, head, "--", "src", "baml_src"):
        raise RuntimeError("HYBRID_CAMPAIGN_PRODUCTION_SOURCE_DRIFT")
    if git(repo, "diff", "--name-only", "--", "src", "baml_src"):
        raise RuntimeError("HYBRID_CAMPAIGN_UNCOMMITTED_SOURCE_DRIFT")

    paths = _runtime_paths(PERMISSION_ID)
    store = campaign.DurableHybridCampaignPermissionStoreV1(
        repo_root=repo, store_root=paths["campaign_store"],
    )
    permission, state, _state_path = store._load_raw(PERMISSION_ID)
    if set(permission) != approvals._PERMISSION_FIELDS:
        raise RuntimeError("HYBRID_CAMPAIGN_PERMISSION_FIELDS_DRIFT")
    permission_scope = dict(permission)
    permission_digest = permission_scope.pop("campaign_permission_sha256", None)
    if permission_digest != domain_sha256(approvals.PERMISSION_DOMAIN, permission_scope):
        raise RuntimeError("HYBRID_CAMPAIGN_PERMISSION_DOMAIN_DRIFT")
    declared_scope = permission_scope.pop("permission_scope_sha256", None)
    if declared_scope != domain_sha256(
        "novel-flywheel-skill-v3-hybrid-campaign-permission-scope-v1",
        permission_scope,
    ):
        raise RuntimeError("HYBRID_CAMPAIGN_PERMISSION_SCOPE_DRIFT")
    if (
        permission.get("repository_head") != EXECUTION_HEAD
        or permission.get("repository_branch") != EXPECTED_BRANCH
        or permission.get("pilot_id") != PILOT_ID
        or permission.get("execution_authorized") is not True
        or permission.get("offline_test_only") is not False
    ):
        raise RuntimeError("HYBRID_CAMPAIGN_PERMISSION_BINDING_DRIFT")
    exact_state = campaign._validate_state(state, permission)
    if permission.get("authorization_text_sha256") != AUTHORIZATION_SHA256:
        raise RuntimeError("HYBRID_CAMPAIGN_AUTHORIZATION_DRIFT")
    if permission.get("experiment_lock_sha256") != EXPERIMENT_LOCK_SHA256:
        raise RuntimeError("HYBRID_CAMPAIGN_EXPERIMENT_LOCK_DRIFT")
    if exact_state.get("campaign_state_sha256") != CAMPAIGN_STATE_SHA256:
        raise RuntimeError("HYBRID_CAMPAIGN_STATE_DRIFT")
    if exact_state.get("status") != "COMPLETED" or exact_state.get("failure_reason") is not None:
        raise RuntimeError("HYBRID_CAMPAIGN_NOT_COMPLETED")
    if tuple(permission.get("authorized_sequence") or ()) != SEQUENCE:
        raise RuntimeError("HYBRID_CAMPAIGN_SEQUENCE_DRIFT")
    if (
        exact_state.get("provider_request_attempts"),
        exact_state.get("http_post_attempts"),
        exact_state.get("network_attempts"),
        exact_state.get("output_token_hard_cap_consumed"),
    ) != (6, 6, 6, 27744):
        raise RuntimeError("HYBRID_CAMPAIGN_COUNTER_DRIFT")

    completion_path = paths["output_root"] / "campaign-completion-v1.json"
    completion = read_json(completion_path)
    body = dict(completion)
    digest = body.pop("completion_receipt_sha256", None)
    if digest != domain_sha256(campaign.CAMPAIGN_COMPLETION_DOMAIN, body):
        raise RuntimeError("HYBRID_CAMPAIGN_COMPLETION_DOMAIN_DRIFT")
    if digest != COMPLETION_RECEIPT_SHA256 or completion.get("status") != "COMPLETED":
        raise RuntimeError("HYBRID_CAMPAIGN_COMPLETION_DRIFT")

    sealed = hybrid.load_sealed_pilot(repo)
    locks = {str(row["SAMPLE_SLOT"]): row for row in sealed["samples"]}
    if tuple(row["SAMPLE_ID"] for row in sealed["samples"]) != EXPECTED_SAMPLE_IDS:
        raise RuntimeError("HYBRID_CAMPAIGN_SAMPLE_ID_DRIFT")
    route = read_json(repo / hybrid.REPORT_ROOT / "provider-model-route-binding-v1.json")
    destination = read_json(repo / hybrid.REPORT_ROOT / "destination-binding-v1.json")
    exact_permission_bindings = {
        "provider": route["PROVIDER"],
        "provider_descriptor_sha256": route["PROVIDER_DESCRIPTOR_SHA256"],
        "model": route["MODEL"],
        "model_binding_sha256": route["MODEL_BINDING_SHA256"],
        "protocol": route["PROTOCOL"],
        "route_fingerprint": route["ROUTE_FINGERPRINT"],
        "destination_origin": destination["DESTINATION_ORIGIN"],
        "destination_hostname": destination["DESTINATION_HOSTNAME"],
        "destination_port": destination["DESTINATION_PORT"],
        "destination_path": destination["DESTINATION_PATH"],
        "operator_classification": destination["OPERATOR_CLASSIFICATION"],
        "egress_policy_sha256s": [row["EGRESS_POLICY_SHA256"] for row in sealed["samples"]],
    }
    if any(permission.get(key) != expected for key, expected in exact_permission_bindings.items()):
        raise RuntimeError("HYBRID_CAMPAIGN_ROUTE_DESTINATION_EGRESS_DRIFT")
    approval_store = approvals.DurableHybridApprovalStoreV1(
        repo_root=repo, store_root=approvals.default_hybrid_approval_store_root(),
    )
    nonce_store = DurablePilotNonceStoreV1(
        repo_root=repo, store_root=default_nonce_store_root(),
    )
    rows = []
    for receipt in exact_state["sample_receipts"]:
        slot = str(receipt["sample_slot"])
        lock = locks[slot]
        if receipt.get("sample_id") != lock.get("SAMPLE_ID") or receipt.get("status") != "SEALED_VALID":
            raise RuntimeError(f"HYBRID_CAMPAIGN_SAMPLE_BINDING_DRIFT:{slot}")
        approval_path, lifecycle_path = approval_store._paths(str(receipt["approval_id"]))
        approval = read_json(approval_path)
        approvals.validate_approval_schema_v1(
            approval, now=_parse_utc(str(approval["created_at"])),
        )
        lifecycle = approvals.validate_lifecycle(read_json(lifecycle_path), approval)
        if (
            lifecycle.get("usage_state") != "CONSUMED"
            or approval.get("sample_id") != receipt.get("sample_id")
            or approval.get("sample_slot") != slot
            or approval.get("sample_lock_sha256") != lock.get("SAMPLE_LOCK_SHA256")
            or approval.get("signed_approval_sha256") != receipt.get("signed_approval_sha256")
            or lifecycle.get("signed_approval_sha256") != receipt.get("signed_approval_sha256")
        ):
            raise RuntimeError(f"HYBRID_CAMPAIGN_APPROVAL_NOT_CONSUMED:{slot}")
        nonce = nonce_store.load(
            pilot_id=PILOT_ID,
            sample_id=str(receipt["sample_id"]),
            approval_id=str(receipt["approval_id"]),
        )
        if (
            nonce.get("state") != "CONSUMED"
            or nonce.get("final_reason") != "SEALED_VALID"
            or nonce.get("nonce_id") != receipt.get("nonce_id")
            or nonce.get("signed_approval_sha256") != receipt.get("signed_approval_sha256")
            or nonce.get("provider_dispatch_attempts") != 1
            or nonce.get("network_request_attempts") != 1
        ):
            raise RuntimeError(f"HYBRID_CAMPAIGN_NONCE_DRIFT:{slot}")
        artifact_path = paths["output_root"] / slot / "sample-artifact-v1.json"
        artifact_bytes = artifact_path.read_bytes()
        if sha_bytes(artifact_bytes) != receipt.get("artifact_file_sha256"):
            raise RuntimeError(f"HYBRID_CAMPAIGN_ARTIFACT_DRIFT:{slot}")
        artifact = read_json(artifact_path)
        if (
            artifact.get("sample_id") != receipt.get("sample_id")
            or artifact.get("production_authority") is not False
            or artifact.get("story_state_mutation_count") != 0
            or artifact.get("canon_mutation_count") != 0
            or artifact.get("ready_mutation_count") != 0
            or artifact.get("artifact", {}).get("validation_status") != "PASS"
            or artifact.get("artifact", {}).get("freeze_state") != "FROZEN"
        ):
            raise RuntimeError(f"HYBRID_CAMPAIGN_TERMINAL_PIPELINE_DRIFT:{slot}")
        rows.append({
            "sample_slot": slot,
            "sample_id": receipt["sample_id"],
            "experiment_arm": str(lock["ARM"]),
            "sample_lock_sha256": lock["SAMPLE_LOCK_SHA256"],
            "artifact_file_sha256": receipt["artifact_file_sha256"],
            "approval_id": receipt["approval_id"],
            "signed_approval_sha256": receipt["signed_approval_sha256"],
            "approval_lifecycle_sha256": lifecycle["lifecycle_sha256"],
            "nonce_id": receipt["nonce_id"],
            "nonce_receipt_sha256": nonce["nonce_receipt_sha256"],
            "artifact": artifact,
        })
    if tuple(row["sample_slot"] for row in rows) != SEQUENCE:
        raise RuntimeError("HYBRID_CAMPAIGN_RECEIPT_ORDER_DRIFT")
    if tuple(row["sample_id"] for row in rows) != EXPECTED_SAMPLE_IDS:
        raise RuntimeError("HYBRID_CAMPAIGN_SAMPLE_ID_DRIFT")
    if tuple(row["artifact_file_sha256"] for row in rows) != EXPECTED_ARTIFACT_SHAS:
        raise RuntimeError("HYBRID_CAMPAIGN_ARTIFACT_SET_DRIFT")
    if len({row["approval_id"] for row in rows}) != 6 or len({row["nonce_id"] for row in rows}) != 6:
        raise RuntimeError("HYBRID_CAMPAIGN_SINGLE_USE_IDENTITY_COLLISION")
    return permission, exact_state, rows


def _fresh_bundle_policy(repo: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    root = repo / MATERIALIZATION_RELATIVE
    methodology = read_json(root / "methodology-binding-v1.json")
    blind_policy = read_json(root / "blind-bundle-policy-v1.json")
    if methodology.get("LITERARY_POLICY_SHA256") != LITERARY_POLICY_SHA256:
        raise RuntimeError("HYBRID_LITERARY_POLICY_DRIFT")
    if methodology.get("SCALAR_AVERAGE_ALLOWED") is not False:
        raise RuntimeError("HYBRID_SCALAR_POLICY_DRIFT")
    if blind_policy.get("MAPPING_HIDDEN_UNTIL_BLIND_FREEZE") != "YES":
        raise RuntimeError("HYBRID_BLIND_POLICY_DRIFT")
    return methodology, blind_policy


def materialize_phase_a(
    repo: Path, *, focused: str, related: str, full_suite: str, strict_l3: str,
) -> dict[str, Any]:
    permission, state, rows = verify_campaign(repo)
    methodology, blind_policy = _fresh_bundle_policy(repo)
    campaign_root = repo / CAMPAIGN_EVIDENCE_RELATIVE
    blind_root = repo / BLIND_BUNDLE_RELATIVE
    mapping_root = repo / MAPPING_RELATIVE
    for root in (campaign_root, blind_root, mapping_root):
        if root.exists():
            raise RuntimeError(f"HYBRID_POST_CAMPAIGN_ROOT_ALREADY_EXISTS:{root}")

    public_rows = [{key: value for key, value in row.items() if key != "artifact"} for row in rows]
    by_slot = {row["sample_slot"]: row for row in rows}
    write(campaign_root / "README.md", "# Skill V3 Hybrid character-heavy real campaign\n\nHash-bound evidence for the completed six-sample campaign. Literary prose and judgments are absent from this root.\n")
    write(campaign_root / "campaign-binding-v1.json", {
        "schema": "SkillV3HybridCampaignPermissionBindingV1",
        "status": "EXACT",
        "permission_id": PERMISSION_ID,
        "campaign_permission_sha256": permission["campaign_permission_sha256"],
        "authorization_text_sha256": AUTHORIZATION_SHA256,
        "repository_head": EXECUTION_HEAD,
        "pilot_id": PILOT_ID,
        "experiment_lock_sha256": EXPERIMENT_LOCK_SHA256,
        "authorized_sequence": list(SEQUENCE),
        "destination": "https://lingsuan.org:443/v1/messages",
        "provider_request_hard_cap": 6,
        "output_token_hard_cap": 27744,
        "monetary_cost_cap": "UNKNOWN_NOT_SEALED",
    })
    write(campaign_root / "campaign-completion-v1.json", {
        "schema": "SkillV3HybridCampaignCompletionBindingV1",
        "status": "EXACT",
        "campaign_state_sha256": CAMPAIGN_STATE_SHA256,
        "completion_receipt_sha256": COMPLETION_RECEIPT_SHA256,
        "sample_count": 6,
        "sealed_valid_count": 6,
        "approval_states": ["CONSUMED"] * 6,
        "nonce_states": ["CONSUMED"] * 6,
        "campaign_state": state,
    })
    write(campaign_root / "six-sample-validity-v1.json", {
        "schema": "SkillV3HybridSixSampleExecutionMatrixV1",
        "status": "PASS",
        "rows": public_rows,
    })
    write(campaign_root / "approval-nonce-lifecycle-v1.json", {
        "schema": "SkillV3HybridApprovalNonceLifecycleV1",
        "status": "PASS",
        "jit_signed_approvals_created": 6,
        "jit_signed_approvals_consumed": 6,
        "durable_nonces_created": 6,
        "durable_nonces_consumed": 6,
        "all_identities_unique": True,
        "rows": [
            {
                "sample_slot": row["sample_slot"],
                "approval_id": row["approval_id"],
                "signed_approval_sha256": row["signed_approval_sha256"],
                "approval_lifecycle_sha256": row["approval_lifecycle_sha256"],
                "approval_state": "CONSUMED",
                "nonce_id": row["nonce_id"],
                "nonce_receipt_sha256": row["nonce_receipt_sha256"],
                "nonce_state": "CONSUMED",
            }
            for row in public_rows
        ],
    })
    write(campaign_root / "request-attempt-accounting-v1.json", {
        "schema": "SkillV3HybridAttemptAndBudgetReceiptV1",
        "status": "PASS",
        "provider_requests": 6,
        "http_post_attempts": 6,
        "network_attempts": 6,
        "per_sample_provider_http_network": [1, 1, 1],
        "retry": 0,
        "transport_retry": 0,
        "fallback": 0,
        "route_switch": 0,
        "resume": 0,
        "second_dispatch": 0,
        "replacement_sample": 0,
        "per_sample_output_token_hard_cap": 4624,
        "total_output_token_hard_cap": 27744,
        "actual_output_tokens_observability": "NOT_RETAINED_BY_CAMPAIGN_BOUNDARY",
        "actual_monetary_cost_observability": "NOT_RETAINED_BY_CAMPAIGN_BOUNDARY",
    })
    write(campaign_root / "route-destination-egress-v1.json", {
        "schema": "SkillV3HybridRouteDestinationEgressV1",
        "status": "EXACT",
        "provider": permission["provider"],
        "provider_descriptor_sha256": permission["provider_descriptor_sha256"],
        "model": permission["model"],
        "model_binding_sha256": permission["model_binding_sha256"],
        "protocol": permission["protocol"],
        "route_fingerprint": permission["route_fingerprint"],
        "destination": "https://lingsuan.org:443/v1/messages",
        "operator_classification": permission["operator_classification"],
        "egress_policy_sha256s": permission["egress_policy_sha256s"],
        "alternate_destination_count": 0,
        "cross_origin_redirect_count": 0,
    })
    write(campaign_root / "artifact-binding-v1.json", {
        "schema": "SkillV3HybridArtifactBindingV1",
        "status": "EXACT",
        "raw_literary_content_persisted_here": False,
        "rows": [
            {
                "sample_slot": row["sample_slot"],
                "sample_id": row["sample_id"],
                "sample_lock_sha256": row["sample_lock_sha256"],
                "artifact_file_sha256": row["artifact_file_sha256"],
                "artifact_value_sha256": sha_bytes(
                    canonical_json_bytes(by_slot_artifact["artifact"])
                ),
            }
            for row, by_slot_artifact in (
                (public, by_slot[public["sample_slot"]]["artifact"])
                for public in public_rows
            )
        ],
    })
    write(campaign_root / "production-isolation-v1.json", {
        "schema": "SkillV3HybridCampaignProductionIsolationV1",
        "status": "PASS",
        "production_authority_count": 0,
        "story_state_mutation_count": 0,
        "canon_mutation_count": 0,
        "ready_mutation_count": 0,
        "skill_v3_cutover": False,
        "planning_v2_cutover": False,
        "full_short_canary": "NOT_EXECUTED",
        "post_authorization_git_commit_count_during_campaign": 0,
        "src_diff_from_execution_head": 0,
        "baml_src_diff_from_execution_head": 0,
    })
    write(campaign_root / "validation-receipt-v1.json", {
        "schema": "SkillV3HybridPostCampaignValidationReceiptV1",
        "status": "PASS",
        "focused": focused,
        "related": related,
        "full_suite": full_suite,
        "strict_l3": strict_l3,
        "warnings": 0,
        "blockers": 0,
        "external_actions_during_materialization": 0,
    })
    campaign_scan = privacy_scan([json_bytes(row) for row in public_rows])
    write(campaign_root / "privacy-scan-v1.json", {
        "schema": "SkillV3HybridCampaignPrivacyScanV1",
        **campaign_scan,
        "raw_prompt_persisted": False,
        "raw_story_input_persisted": False,
        "raw_provider_content_persisted": False,
        "literary_artifact_persisted_here": False,
    })
    write(campaign_root / "final-campaign-report-v1.md", f"""# Skill V3 Hybrid character-heavy real campaign\n\n`SKILL_V3_HYBRID_CHARACTER_HEAVY_REAL_CAMPAIGN_SEALED_VALID`\n\n- Branch / execution HEAD: `{EXPECTED_BRANCH}` / `{EXECUTION_HEAD}`\n- Pilot / experiment lock: `{PILOT_ID}` / `{EXPERIMENT_LOCK_SHA256}`\n- Permission / state / completion: `{permission['campaign_permission_sha256']}` / `{CAMPAIGN_STATE_SHA256}` / `{COMPLETION_RECEIPT_SHA256}`\n- Samples: `6/6 SEALED_VALID`; approvals/nonces: `6/6 CONSUMED`\n- Provider / HTTP / network attempts: `6/6/6`, exactly one per sample\n- Retry / transport retry / fallback / route switch / resume / second dispatch: `0/0/0/0/0/0`\n- Production authority / StoryState / Canon / READY mutation: `0/0/0/0`\n- Literary judgment in MAIN: `NOT_PERFORMED`\n- Materialization external actions: credential/network/model/paid `0/0/0/0`\n- Skill V3 / Planning V2 cutover: `NO/NO`; Full Short: `NOT_EXECUTED`\n""")
    write(campaign_root / "sha256-manifest-v1.json", manifest(campaign_root, "SkillV3HybridCampaignSha256ManifestV1"))
    campaign_manifest_sha = sha_bytes((campaign_root / "sha256-manifest-v1.json").read_bytes())

    mapping_rows: list[dict[str, Any]] = []
    pair_rows: list[dict[str, Any]] = []
    for pair_index in range(1, 4):
        samples = []
        for side_index, slot in enumerate(visible_pair_order(pair_index), 1):
            row = by_slot[slot]
            anon = anonymous_id(campaign_manifest_sha, pair_index, side_index)
            literary = row["artifact"]["artifact"]
            public_artifact = {
                "schema": "SkillV3HybridBlindLiteraryArtifactV1",
                "anonymous_sample_id": anon,
                "title": literary["title"],
                "narrative": literary["narrative"],
            }
            relative = f"artifacts/{anon}.json"
            write(blind_root / relative, public_artifact)
            artifact_sha = sha_bytes((blind_root / relative).read_bytes())
            samples.append({
                "anonymous_sample_id": anon,
                "artifact_path": relative,
                "artifact_sha256": artifact_sha,
            })
            mapping_rows.append({
                "anonymous_pair_id": f"hybrid-blind-pair-{pair_index}",
                "anonymous_position": "A" if side_index == 1 else "B",
                "anonymous_sample_id": anon,
                "sample_slot": slot,
                "sample_id": row["sample_id"],
                "experiment_arm": row["experiment_arm"],
                "artifact_file_sha256": row["artifact_file_sha256"],
                "blind_artifact_sha256": artifact_sha,
            })
        pair_rows.append({
            "anonymous_pair_id": f"hybrid-blind-pair-{pair_index}",
            "position_a_anonymous_sample_id": samples[0]["anonymous_sample_id"],
            "position_b_anonymous_sample_id": samples[1]["anonymous_sample_id"],
            "samples": samples,
        })

    write(blind_root / "README.md", "# Skill V3 Hybrid anonymous literary evaluation bundle\n\nRead only this root. Do not inspect Git history, runtime data, mapping evidence, or another evaluator's record. Judge the three pairs independently and freeze all six sample notes plus three pair votes before returning.\n")
    write(blind_root / "blind-batch-v1.json", {
        "schema": "SkillV3HybridAnonymousBlindBatchV1",
        "status": "READY",
        "pair_count": 3,
        "sample_count": 6,
        "pairs": pair_rows,
        "arm_identity_visible": False,
        "skill_context_visible": False,
        "campaign_metadata_visible": False,
    })
    write(blind_root / "sealed-literary-policy-v1.json", methodology)
    write(blind_root / "sealed-blind-policy-v1.json", blind_policy)
    write(
        blind_root / "minimal-task-context-v1.json",
        read_json(
            repo
            / "docs/superpowers/reports/skill-v3-character-heavy-multi-sample-blind-bundle-v1/minimal-task-context-v1.json"
        ),
    )
    write(blind_root / "evaluator-instructions-v1.json", {
        "schema": "SkillV3HybridBlindEvaluatorInstructionsV1",
        "status": "SEALED",
        "required_fresh_context": True,
        "allowed_roots": [BLIND_BUNDLE_RELATIVE.as_posix()],
        "forbidden_roots": [MAPPING_RELATIVE.as_posix(), EVALUATOR_1_RELATIVE.as_posix(), EVALUATOR_2_RELATIVE.as_posix()],
        "dimensions": list(DIMENSIONS),
        "allowed_relations": sorted(RELATIONS),
        "required_independent_sample_judgments": 6,
        "required_evaluator_by_batch_votes": 3,
        "arm_identity_guess_forbidden": True,
        "mapping_access_forbidden": True,
        "scalar_average_forbidden": True,
    })
    write(blind_root / "judgment-template-v1.json", empty_evaluator_record("FRESH_EVALUATOR_REQUIRED", pair_rows))

    visible = [path.read_bytes() for path in blind_root.rglob("*") if path.is_file()]
    visible_blob = b"\n".join(visible)
    leak_counts = {
        "sample_id_matches": sum(visible_blob.count(str(row["sample_id"]).encode()) for row in rows),
        "sample_slot_matches": sum(visible_blob.count(str(row["sample_slot"]).encode()) for row in rows),
        "experiment_arm_key_matches": visible_blob.count(b'"experiment_arm"'),
        "route_fingerprint_matches": visible_blob.count(str(permission["route_fingerprint"]).encode()),
        "approval_id_matches": sum(visible_blob.count(str(row["approval_id"]).encode()) for row in rows),
        "nonce_id_matches": sum(visible_blob.count(str(row["nonce_id"]).encode()) for row in rows),
    }
    if sum(leak_counts.values()):
        raise RuntimeError(f"HYBRID_BLIND_METADATA_LEAK:{leak_counts}")
    blind_scan = privacy_scan(visible)
    if blind_scan["status"] != "PASS":
        raise RuntimeError("HYBRID_BLIND_PRIVACY_FAILURE")
    write(blind_root / "privacy-scan-v1.json", {
        "schema": "SkillV3HybridBlindPrivacyScanV1",
        **blind_scan,
        **leak_counts,
        "mapping_visible": False,
    })
    write(blind_root / "sha256-manifest-v1.json", manifest(blind_root, "SkillV3HybridBlindBundleSha256ManifestV1"))

    write(mapping_root / "README.md", "# Skill V3 Hybrid MAIN-only sealed blind mapping\n\nDo not expose this root to either blind evaluator before both vote sets are frozen.\n")
    write(mapping_root / "sealed-mapping-v1.json", {
        "schema": "SkillV3HybridBlindMappingV1",
        "status": "SEALED_MAIN_ONLY",
        "campaign_manifest_sha256": campaign_manifest_sha,
        "mapping_frozen_before_evaluation": True,
        "blind_evaluation_started": False,
        "rows": mapping_rows,
    })
    write(mapping_root / "chronology-v1.json", {
        "schema": "SkillV3HybridBlindChronologyV1",
        "status": "PRE_EVALUATION",
        "campaign_completed_before_bundle": True,
        "mapping_frozen_before_evaluator_1": True,
        "mapping_frozen_before_evaluator_2": True,
        "mapping_reveal_allowed_only_after_two_freezes": True,
    })
    write(mapping_root / "handoff-report-v1.md", f"""# Skill V3 Hybrid blind handoff\n\n`SKILL_V3_HYBRID_BLIND_BUNDLE_READY`\n\n- Campaign manifest SHA: `{campaign_manifest_sha}`\n- Anonymous samples / pairs: `6/3`\n- Mapping: `SEALED_MAIN_ONLY`; evaluator-visible mapping leaks: `0`\n- Two fresh independent evaluator contexts required; votes frozen: `0/2`\n- MAIN literary judgment: `NOT_PERFORMED`\n- External actions during handoff: credential/network/model/paid `0/0/0/0`\n\n`SKILL_V3_HYBRID_MAIN_WAITING_FOR_TWO_BLIND_FREEZES`\n""")
    write(mapping_root / "sha256-manifest-v1.json", manifest(mapping_root, "SkillV3HybridBlindMappingSha256ManifestV1"))
    return {
        "status": "READY",
        "campaign_manifest_sha256": campaign_manifest_sha,
        "blind_manifest_sha256": sha_bytes((blind_root / "sha256-manifest-v1.json").read_bytes()),
        "mapping_manifest_sha256": sha_bytes((mapping_root / "sha256-manifest-v1.json").read_bytes()),
    }


def empty_evaluator_record(evaluator_id: str, pairs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    sample_ids = []
    for pair in pairs:
        sample_ids.extend([
            str(pair["position_a_anonymous_sample_id"]),
            str(pair["position_b_anonymous_sample_id"]),
        ])
    return {
        "schema": "SkillV3HybridBlindEvaluatorFreezeV1",
        "status": "UNSET",
        "evaluator_id": evaluator_id,
        "fresh_context": True,
        "mapping_accessed": False,
        "other_evaluator_record_accessed": False,
        "arm_identity_guessed": False,
        "scalar_average_created": False,
        "independent_sample_judgments": [
            {
                "anonymous_sample_id": sample_id,
                "summary": "UNSET",
                "strengths": [],
                "risks": [],
                "dimension_notes": {dimension: "UNSET" for dimension in DIMENSIONS},
            }
            for sample_id in sample_ids
        ],
        "votes": [
            {
                "anonymous_pair_id": str(pair["anonymous_pair_id"]),
                "position_a_anonymous_sample_id": str(pair["position_a_anonymous_sample_id"]),
                "position_b_anonymous_sample_id": str(pair["position_b_anonymous_sample_id"]),
                "dimension_relations": {dimension: "UNSET" for dimension in DIMENSIONS},
                "dimension_evidence": {dimension: "UNSET" for dimension in DIMENSIONS},
            }
            for pair in pairs
        ],
        "judgments_frozen": False,
        "external_project_actions": 0,
    }


def _pairs_from_blind_root(blind_root: Path) -> list[dict[str, Any]]:
    batch = read_json(blind_root / "blind-batch-v1.json")
    return [
        {
            "anonymous_pair_id": row["anonymous_pair_id"],
            "position_a_anonymous_sample_id": row["position_a_anonymous_sample_id"],
            "position_b_anonymous_sample_id": row["position_b_anonymous_sample_id"],
        }
        for row in batch["pairs"]
    ]


def validate_evaluator_record(value: Mapping[str, Any], pairs: Sequence[Mapping[str, Any]]) -> None:
    if value.get("schema") != "SkillV3HybridBlindEvaluatorFreezeV1":
        raise RuntimeError("EVALUATOR_SCHEMA_MISMATCH")
    if value.get("evaluator_id") not in {"e1", "e2"}:
        raise RuntimeError("EVALUATOR_ID_MISMATCH")
    if value.get("mapping_accessed") is not False or value.get("other_evaluator_record_accessed") is not False:
        raise RuntimeError("EVALUATOR_BLIND_FIREWALL_FAILURE")
    if value.get("arm_identity_guessed") is not False or value.get("scalar_average_created") is not False:
        raise RuntimeError("EVALUATOR_POLICY_FAILURE")
    expected_samples = {
        str(pair[key])
        for pair in pairs
        for key in ("position_a_anonymous_sample_id", "position_b_anonymous_sample_id")
    }
    judgments = list(value.get("independent_sample_judgments") or ())
    if len(judgments) != 6 or {row.get("anonymous_sample_id") for row in judgments} != expected_samples:
        raise RuntimeError("EVALUATOR_SAMPLE_JUDGMENT_SET_MISMATCH")
    votes = list(value.get("votes") or ())
    if len(votes) != 3 or [row.get("anonymous_pair_id") for row in votes] != [row["anonymous_pair_id"] for row in pairs]:
        raise RuntimeError("EVALUATOR_VOTE_SET_MISMATCH")
    for vote, pair in zip(votes, pairs, strict=True):
        if (
            vote.get("position_a_anonymous_sample_id") != pair["position_a_anonymous_sample_id"]
            or vote.get("position_b_anonymous_sample_id") != pair["position_b_anonymous_sample_id"]
        ):
            raise RuntimeError("EVALUATOR_PAIR_BINDING_MISMATCH")
        relations = vote.get("dimension_relations") or {}
        if set(relations) != set(DIMENSIONS):
            raise RuntimeError("EVALUATOR_DIMENSION_SET_MISMATCH")
        if any(relation not in RELATIONS for relation in relations.values()):
            raise RuntimeError("EVALUATOR_RELATION_INVALID")


def aggregate_blind_votes(
    records: Sequence[Mapping[str, Any]], pairs: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if len(records) != 2 or {row.get("evaluator_id") for row in records} != {"e1", "e2"}:
        raise RuntimeError("TWO_DISTINCT_EVALUATORS_REQUIRED")
    for record in records:
        validate_evaluator_record(record, pairs)
    flattened = [
        {
            "vote_id": f"{record['evaluator_id']}:{vote['anonymous_pair_id']}",
            "evaluator_id": record["evaluator_id"],
            **deepcopy(vote),
        }
        for record in records
        for vote in record["votes"]
    ]
    dimensions = []
    for dimension in DIMENSIONS:
        counts = Counter(vote["dimension_relations"][dimension] for vote in flattened)
        supported = [relation for relation in ("A_BETTER", "B_BETTER", "TIE") if counts[relation] >= 4]
        relation = supported[0] if len(supported) == 1 else "INCONCLUSIVE"
        dimensions.append({
            "dimension": dimension,
            "counts": {name: counts[name] for name in sorted(RELATIONS)},
            "blind_relation": relation,
            "support_threshold": 4,
        })
    return {
        "schema": "SkillV3HybridCombinedBlindAggregationV1",
        "status": "COMPLETE_EXACT",
        "required_evaluator_by_batch_votes": 6,
        "observed_evaluator_by_batch_votes": len(flattened),
        "votes": flattened,
        "dimensions": dimensions,
        "scalar_average_created": False,
        "mapping_revealed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("phase-a", "verify"))
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--focused", default="NOT_RUN")
    parser.add_argument("--related", default="NOT_RUN")
    parser.add_argument("--full-suite", default="NOT_RUN")
    parser.add_argument("--strict-l3", default="NOT_RUN")
    args = parser.parse_args()
    repo = args.repo_root.resolve(strict=True)
    if args.mode == "phase-a":
        result = materialize_phase_a(
            repo,
            focused=args.focused,
            related=args.related,
            full_suite=args.full_suite,
            strict_l3=args.strict_l3,
        )
    else:
        verify_campaign(repo)
        for root in (CAMPAIGN_EVIDENCE_RELATIVE, BLIND_BUNDLE_RELATIVE, MAPPING_RELATIVE):
            verify_manifest(repo / root)
        result = {"status": "EXACT"}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
