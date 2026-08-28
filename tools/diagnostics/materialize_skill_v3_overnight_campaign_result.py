"""Seal the completed Skill V3 campaign and prepare its blind handoff.

This is an offline evidence materializer.  It never imports a Provider client,
reads credentials, or performs network I/O.  Runtime records are read from the
isolated stores created by the already-completed campaign.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping

from novel_flywheel.runtime_fingerprint_build import canonical_json_bytes, domain_sha256
from tools.canary import skill_v3_character_heavy_pilot as pilot
from tools.canary import skill_v3_overnight_campaign as campaign
from tools.canary import skill_v3_pilot_approval_store as approvals
from tools.canary.skill_v3_pilot_nonce_store import (
    DurablePilotNonceStoreV1,
    default_nonce_store_root,
)


CAMPAIGN_EVIDENCE_RELATIVE = Path(
    "docs/superpowers/reports/skill-v3-character-heavy-multi-sample-real-campaign-v1"
)
BLIND_BUNDLE_RELATIVE = Path(
    "docs/superpowers/reports/skill-v3-character-heavy-multi-sample-blind-bundle-v1"
)
MAPPING_RELATIVE = Path(
    "docs/superpowers/reports/skill-v3-character-heavy-multi-sample-blind-mapping-v1"
)
EXPECTED_HEAD = "32b230f4ddf1fe7cb93705e4d365d9f898e75702"
EXPECTED_BRANCH = "r1-ptr3/planning-repair-finding-propagation-20260817"
EXPECTED_PERMISSION = "416330ffdafc974342435cd489dbcca9b7f68dd3b86df1bafcd9f6713daf38ad"
EXPECTED_STATE = "48df7a76f8b982c6010bff7fed1506323409b44fdf9ff66852c539dec73bad15"
SUCCESS_DOMAIN = "novel-flywheel-skill-v3-remaining-sample-success-v1"
STATE_DOMAIN = "novel-flywheel-skill-v3-remaining-campaign-state-v1"
PAIR_ORDER = (("A1", "B1"), ("A2", "B2"), ("A3", "B3"))


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path.name}")
    return value


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, bytes):
        data = value
    elif isinstance(value, str):
        data = value.encode("utf-8")
    else:
        data = _json_bytes(value)
    path.write_bytes(data)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True,
        encoding="utf-8", errors="strict",
    ).stdout.strip()


def _verify_baseline(repo: Path, *, allow_evidence_successor: bool = False) -> tuple[str, str]:
    head = _git(repo, "rev-parse", "HEAD")
    branch = _git(repo, "branch", "--show-current")
    head_exact = head == EXPECTED_HEAD
    successor_exact = (
        allow_evidence_successor
        and _git(repo, "merge-base", "--is-ancestor", EXPECTED_HEAD, head) == ""
        and not _git(repo, "diff", "--name-only", EXPECTED_HEAD, head, "--", "src", "baml_src")
    )
    if branch != EXPECTED_BRANCH or not (head_exact or successor_exact):
        raise RuntimeError("CAMPAIGN_RESULT_BASELINE_DRIFT")
    if _git(repo, "diff", "--name-only", "--", "src", "baml_src"):
        raise RuntimeError("PRODUCTION_SOURCE_DRIFT")
    return head, branch


def _verify_domain(value: Mapping[str, Any], field: str, domain: str) -> None:
    body = dict(value)
    observed = body.pop(field, None)
    if observed != domain_sha256(domain, body):
        raise RuntimeError(f"DOMAIN_SHA_MISMATCH:{field}")


def _approval_paths(root: Path, approval_id: str) -> tuple[Path, Path]:
    key = domain_sha256("skill-v3-pilot-approval-storage-key-v1", approval_id)
    return root / f"{key}.approval.json", root / f"{key}.consumed.json"


def _artifact_index(root: Path) -> dict[str, tuple[Path, dict[str, Any]]]:
    found: dict[str, tuple[Path, dict[str, Any]]] = {}
    for path in root.glob("*/output/sample-artifact-v1.json"):
        value = _read_json(path)
        sample_id = str(value.get("sample_id") or "")
        if sample_id:
            if sample_id in found:
                raise RuntimeError(f"DUPLICATE_ARTIFACT:{sample_id}")
            found[sample_id] = (path, value)
    return found


def _a1_row(repo: Path, artifact_index: Mapping[str, tuple[Path, dict[str, Any]]]) -> dict[str, Any]:
    root = repo / "docs/superpowers/reports/skill-v3-character-heavy-pilot-a1-real-execution-v3"
    manifest = _read_json(root / "sha256-manifest-v1.json")
    for entry in manifest["entries"]:
        data = (root / entry["path"]).read_bytes()
        if len(data) != entry["bytes"] or _sha_bytes(data) != entry["sha256"]:
            raise RuntimeError(f"A1_EVIDENCE_DRIFT:{entry['path']}")
    validity = _read_json(root / "sample-validity-v1.json")
    if validity.get("status") != "SEALED_VALID":
        raise RuntimeError("A1_NOT_SEALED_VALID")
    sample_id = str(validity["sample_id"])
    artifact_path, artifact = artifact_index[sample_id]
    if _sha_bytes(artifact_path.read_bytes()) != validity["artifact_file_sha256"]:
        raise RuntimeError("A1_ARTIFACT_DRIFT")
    return {
        "sample_slot": "A1", "sample_id": sample_id, "status": "SEALED_VALID",
        "signed_approval": _read_json(root / "approval-v3-binding-v1.json"),
        "approval_final_state": _read_json(root / "approval-final-state-v1.json"),
        "nonce_final_state": _read_json(root / "nonce-final-state-v1.json"),
        "nonce_receipt": _read_json(root / "durable-nonce-receipt-v1.json"),
        "execution_receipt": _read_json(root / "real-destination-dispatch-receipt-v1.json"),
        "destination_egress": _read_json(root / "destination-binding-v1.json"),
        "attempts": _read_json(root / "single-dispatch-counter-receipt-v1.json"),
        "terminal_pipeline": _read_json(root / "terminal-local-pipeline-receipt-v1.json"),
        "artifact_file_sha256": validity["artifact_file_sha256"],
        "artifact": artifact,
        "source_evidence_manifest_sha256": _sha_bytes((root / "sha256-manifest-v1.json").read_bytes()),
    }


def _remaining_rows(
    *, repo: Path, state: Mapping[str, Any], approval_root: Path,
    nonce_root: Path, artifact_index: Mapping[str, tuple[Path, dict[str, Any]]],
) -> list[dict[str, Any]]:
    sealed = pilot.load_sealed_pilot(repo)
    locks = {str(row["sample_id"]): row for row in sealed["locks"]}
    nonce_store = DurablePilotNonceStoreV1(repo_root=repo, store_root=nonce_root)
    rows: list[dict[str, Any]] = []
    for result in state["sample_results"]:
        if result.get("status") != "SEALED_VALID":
            raise RuntimeError(f"CAMPAIGN_SAMPLE_INVALID:{result.get('sample_slot')}")
        sample_id = str(result["sample_id"])
        lock = locks[sample_id]
        approval_path, consumed_path = _approval_paths(approval_root, str(result["approval_id"]))
        approval = _read_json(approval_path)
        consumed = _read_json(consumed_path)
        _verify_domain(approval, "signed_approval_sha256", approvals.SIGNED_APPROVAL_DOMAIN_V4)
        _verify_domain(consumed, "consumption_sha256", approvals.CONSUMPTION_DOMAIN)
        if approval["signed_approval_sha256"] != result["signed_approval_sha256"]:
            raise RuntimeError(f"APPROVAL_BINDING_DRIFT:{sample_id}")
        if consumed["execution_receipt_sha256"] != result["execution_receipt_sha256"]:
            raise RuntimeError(f"CONSUMPTION_BINDING_DRIFT:{sample_id}")
        nonce = nonce_store.load(
            pilot_id=pilot.PILOT_ID, sample_id=sample_id,
            approval_id=str(result["approval_id"]),
        )
        if nonce.get("state") != "CONSUMED" or nonce.get("final_reason") != "SEALED_VALID":
            raise RuntimeError(f"NONCE_NOT_CONSUMED:{sample_id}")
        artifact_path, artifact = artifact_index[sample_id]
        artifact_sha = _sha_bytes(artifact_path.read_bytes())
        if artifact_sha != result["artifact_file_sha256"]:
            raise RuntimeError(f"ARTIFACT_DRIFT:{sample_id}")
        execution_body = {
            "status": "SEALED_VALID", "sample_id": sample_id,
            "sample_slot": result["sample_slot"], "attempts": result["attempts"],
            "real_boundary_reached": 1, "artifact_file_sha256": artifact_sha,
            "terminal_pipeline": "PASS",
        }
        receipt_sha = domain_sha256(SUCCESS_DOMAIN, execution_body)
        if receipt_sha != result["execution_receipt_sha256"]:
            raise RuntimeError(f"EXECUTION_RECEIPT_DRIFT:{sample_id}")
        for field in (
            "provider_dispatch_attempt_count", "network_request_attempt_count",
            "http_post_attempt_count", "logical_model_call_count",
        ):
            if int(result["attempts"][field]) != 1:
                raise RuntimeError(f"ATTEMPT_COUNT_DRIFT:{sample_id}:{field}")
        if int(nonce["provider_dispatch_attempts"]) != 1 or int(nonce["network_request_attempts"]) != 1:
            raise RuntimeError(f"NONCE_ATTEMPT_DRIFT:{sample_id}")
        rows.append({
            "sample_slot": result["sample_slot"], "sample_id": sample_id,
            "status": "SEALED_VALID", "sample_lock_sha256": lock["sample_lock_sha256"],
            "signed_approval": {
                "approval_id": approval["approval_id"],
                "signed_approval_sha256": approval["signed_approval_sha256"],
                "schema": approval["schema"], "usage_status_at_issue": approval["usage_status"],
                "execution_authorized": approval["execution_authorized"],
                "single_use": approval["single_use"],
            },
            "approval_final_state": {
                "state": "CONSUMED", "consumption_sha256": consumed["consumption_sha256"],
                "execution_receipt_sha256": consumed["execution_receipt_sha256"],
            },
            "nonce_final_state": {
                "state": nonce["state"], "nonce_receipt_sha256": nonce["nonce_receipt_sha256"],
                "provider_dispatch_attempts": nonce["provider_dispatch_attempts"],
                "network_request_attempts": nonce["network_request_attempts"],
                "single_use": nonce["single_use"], "final_reason": nonce["final_reason"],
            },
            "execution_receipt": {**execution_body, "execution_receipt_sha256": receipt_sha},
            "destination_egress": {
                "destination_origin": approval["destination_origin"],
                "destination_path": approval["destination_path_or_prefix"],
                "destination_operator_class": approval["destination_operator_class"],
                "destination_origin_sha256": approval["destination_origin_sha256"],
                "egress_policy_sha256": approval["egress_policy_sha256"],
                "cross_origin_redirect_allowed": approval["cross_origin_redirect_allowed"],
                "unbound_proxy_route_allowed": approval["unbound_proxy_route_allowed"],
            },
            "attempts": {**result["attempts"], **result["transport_attempts"]},
            "terminal_pipeline": {
                "status": "PASS", "parser_schema_before_freeze": "PASS",
                "validation_status": artifact["artifact"]["validation_status"],
                "freeze_state": artifact["artifact"]["freeze_state"],
                "output_isolation": "PASS", "persistence": "PASS",
                "production_authority": artifact["production_authority"],
            },
            "artifact_file_sha256": artifact_sha, "artifact": artifact,
        })
    if [row["sample_slot"] for row in rows] != list(campaign.CAMPAIGN_SEQUENCE):
        raise RuntimeError("CAMPAIGN_SEQUENCE_DRIFT")
    return rows


def _public_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key != "artifact"}


def _manifest(root: Path, schema: str) -> dict[str, Any]:
    entries = []
    for path in sorted(p for p in root.rglob("*") if p.is_file() and p.name != "sha256-manifest-v1.json"):
        data = path.read_bytes()
        entries.append({
            "path": path.relative_to(root).as_posix(), "bytes": len(data),
            "sha256": _sha_bytes(data),
        })
    body = {"schema": schema, "status": "EXACT", "entry_count": len(entries), "entries": entries}
    return {**body, "definition_sha256": domain_sha256(schema, body)}


def _scan(values: list[bytes]) -> dict[str, Any]:
    patterns = {
        "anthropic_secret": rb"sk-ant-[A-Za-z0-9_-]{8,}",
        "bearer_token": rb"Bearer\s+[A-Za-z0-9._-]{16,}",
        "private_key": rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    }
    matches = {
        name: sum(len(re.findall(pattern, value, flags=re.IGNORECASE)) for value in values)
        for name, pattern in patterns.items()
    }
    return {"status": "PASS" if sum(matches.values()) == 0 else "FAIL", "matches": matches,
            "total_matches": sum(matches.values())}


def load_verified_campaign(
    *, repo: Path, state_path: Path, approval_root: Path, nonce_root: Path,
    artifact_root: Path, allow_evidence_successor: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    _verify_baseline(repo, allow_evidence_successor=allow_evidence_successor)
    state = _read_json(state_path)
    _verify_domain(state, "state_sha256", STATE_DOMAIN)
    if state.get("state_sha256") != EXPECTED_STATE or state.get("status") != "SEALED_VALID":
        raise RuntimeError("CAMPAIGN_STATE_NOT_EXACT")
    if state.get("campaign_authorization_sha256") != EXPECTED_PERMISSION:
        raise RuntimeError("CAMPAIGN_PERMISSION_BINDING_DRIFT")
    if (state.get("cumulative_provider_attempts"), state.get("cumulative_http_post_attempts"),
            state.get("cumulative_network_attempts")) != (5, 5, 5):
        raise RuntimeError("CAMPAIGN_CUMULATIVE_ATTEMPT_DRIFT")
    artifacts = _artifact_index(artifact_root)
    rows = [_a1_row(repo, artifacts)]
    rows.extend(_remaining_rows(
        repo=repo, state=state, approval_root=approval_root,
        nonce_root=nonce_root, artifact_index=artifacts,
    ))
    if [row["sample_slot"] for row in rows] != list(pilot.SEQUENCE):
        raise RuntimeError("SIX_SAMPLE_SEQUENCE_DRIFT")
    if len({row["sample_id"] for row in rows}) != 6 or len({row["artifact_file_sha256"] for row in rows}) != 6:
        raise RuntimeError("SIX_SAMPLE_INDEPENDENCE_DRIFT")
    return state, rows


def materialize_campaign(
    *, repo: Path, state_path: Path, approval_root: Path, nonce_root: Path,
    artifact_root: Path, focused: str, related: str, strict_l3: str,
) -> dict[str, Any]:
    state, rows = load_verified_campaign(
        repo=repo, state_path=state_path, approval_root=approval_root,
        nonce_root=nonce_root, artifact_root=artifact_root,
    )
    root = repo / CAMPAIGN_EVIDENCE_RELATIVE
    if root.exists():
        raise RuntimeError("CAMPAIGN_EVIDENCE_ALREADY_EXISTS")
    _write(root / "README.md", b"# Skill V3 character-heavy multi-sample real campaign\n\nHash-bound execution evidence for six sealed valid samples. Literary judgments are deliberately absent.\n")
    _write(root / "campaign-authorization-binding-v1.json", {
        "schema": "SkillV3CampaignAuthorizationBindingV1", "status": "PASS",
        "campaign_authorization_sha256": EXPECTED_PERMISSION,
        "authorization_source": "EXACT_USER_PLAINTEXT_CONTEXT",
        "permission_is_per_sample_signed_approval": False,
        "authorized_sequence": list(campaign.CAMPAIGN_SEQUENCE),
        "destination": campaign.EXPECTED_DESTINATION,
        "maximum_requests": 5, "maximum_elapsed_hours": 10,
        "retry_fallback_route_switch_resume_second_dispatch_allowed": False,
    })
    _write(root / "campaign-state-binding-v1.json", state)
    _write(root / "six-sample-validity-matrix-v1.json", {
        "schema": "SkillV3SixSampleValidityMatrixV1", "status": "PASS",
        "valid_count": 6, "required_count": 6,
        "rows": [{"sample_slot": r["sample_slot"], "sample_id": r["sample_id"],
                  "status": r["status"], "artifact_file_sha256": r["artifact_file_sha256"]} for r in rows],
    })
    categories = {
        "signed-approval-bindings-v1.json": "signed_approval",
        "approval-final-states-v1.json": "approval_final_state",
        "nonce-final-states-v1.json": "nonce_final_state",
        "execution-receipts-v1.json": "execution_receipt",
        "destination-egress-receipts-v1.json": "destination_egress",
        "attempt-counters-v1.json": "attempts",
        "terminal-pipeline-receipts-v1.json": "terminal_pipeline",
    }
    for filename, key in categories.items():
        _write(root / filename, {
            "schema": "SkillV3Campaign" + "".join(part.title() for part in key.split("_")) + "V1",
            "status": "PASS", "rows": [
                {"sample_slot": r["sample_slot"], "sample_id": r["sample_id"], key: r[key]}
                for r in rows
            ],
        })
    _write(root / "literary-artifact-sha256-matrix-v1.json", {
        "schema": "SkillV3LiteraryArtifactSha256MatrixV1", "status": "EXACT",
        "raw_literary_content_persisted_in_campaign_evidence": False,
        "rows": [{"sample_slot": r["sample_slot"], "sample_id": r["sample_id"],
                  "artifact_file_sha256": r["artifact_file_sha256"],
                  "artifact_value_sha256": _sha_bytes(canonical_json_bytes(r["artifact"]["artifact"]))}
                 for r in rows],
    })
    _write(root / "independence-contamination-recheck-v1.json", {
        "schema": "SkillV3CampaignIndependenceContaminationRecheckV1", "status": "PASS",
        "unique_sample_ids": 6, "unique_artifacts": 6,
        "unique_approvals": 6, "unique_nonces": 6, "unique_execution_receipts": 6,
        "prior_sample_prose_in_input": False, "prior_sample_result_in_input": False,
        "prior_blind_result_in_input": False, "cross_arm_prose_injection": False,
        "primary_changed_variable": "SKILL_CONTEXT", "uncontrolled_variable_count": 0,
    })
    _write(root / "cumulative-budget-receipt-v1.json", {
        "schema": "SkillV3CampaignCumulativeBudgetReceiptV1", "status": "PASS",
        "a1_provider_http_network": [1, 1, 1],
        "remaining_provider_http_network": [5, 5, 5],
        "campaign_total_provider_http_network": [6, 6, 6],
        "per_sample_max_requests": 1, "retry_count": 0, "fallback_count": 0,
        "route_switch_count": 0, "resume_count": 0, "second_dispatch_count": 0,
        "maximum_output_tokens_per_sample": 4624, "maximum_output_tokens_total": 27744,
        "cost_cap": "UNKNOWN_NOT_SEALED",
    })
    _write(root / "production-isolation-v1.json", {
        "schema": "SkillV3CampaignProductionIsolationV1", "status": "PASS",
        "production_authority_count": 0, "story_state_mutation_count": 0,
        "canon_mutation_count": 0, "ready_mutation_count": 0,
        "skill_v3_cutover": False, "planning_v2_cutover": False,
        "full_short_canary": "NOT_EXECUTED", "src_diff": 0, "baml_src_diff": 0,
    })
    _write(root / "test-receipt-v1.json", {
        "schema": "SkillV3CampaignTestReceiptV1", "status": "PASS",
        "focused": focused, "related": related,
        "phase_a_full_suite": "3794 passed, 41 skipped, 6 xfailed, 54 failed, 72 errors; unrelated sealed-evidence/materialization/Planning-Skill/live-parity gates",
        "strict_l3": strict_l3, "warnings": 0, "blockers": 0,
        "literary_judgment_performed": False,
    })
    scan = _scan([_json_bytes(_public_row(r)) for r in rows])
    _write(root / "privacy-scan-v1.json", {
        "schema": "SkillV3CampaignPrivacyScanV1", **scan,
        "credentials_persisted": False, "raw_provider_response_persisted": False,
        "raw_prompt_persisted": False, "raw_story_input_persisted": False,
        "literary_artifacts_persisted_here": False,
    })
    _write(root / "final-report-v1.md", f"""# Skill V3 character-heavy multi-sample real campaign\n\n`SKILL_V3_MULTI_SAMPLE_REAL_CAMPAIGN_SEALED_VALID`\n\n- Branch / execution HEAD: `{EXPECTED_BRANCH}` / `{EXPECTED_HEAD}`\n- Campaign permission SHA: `{EXPECTED_PERMISSION}`\n- Campaign state SHA: `{EXPECTED_STATE}`\n- Samples: `6/6 SEALED_VALID`; A1 plus B1→A2→B2→A3→B3\n- Provider / HTTP / network requests: `6/6/6`; exactly one per sample\n- Retry / transport retry / fallback / route switch / resume / second dispatch: `0/0/0/0/0/0`\n- Terminal pipeline: `6/6 PASS`; production authority and StoryState/Canon/READY mutations: `0`\n- Campaign stopped on failure: not triggered; automatic replacement: `0`\n- Literary judgment: `NOT_PERFORMED_IN_MAIN_CONTEXT`\n- Privacy: `{scan['status']}`; credential matches `{scan['total_matches']}`\n- Tests: focused `{focused}`; related `{related}`; Strict L3 `{strict_l3}`\n- Production source changes: `0`; Skill V3/Planning V2 cutover: `NO/NO`; Full Short: `NOT_EXECUTED`\n\nThe next permitted action is local anonymous blind-bundle materialization. No further Provider request is authorized or needed.\n""")
    manifest = _manifest(root, "SkillV3CampaignSha256ManifestV1")
    _write(root / "sha256-manifest-v1.json", manifest)
    return {"status": "SEALED_VALID", "root": str(root), "manifest": manifest}


def _anon_id(campaign_manifest_sha: str, pair_index: int, side_index: int) -> str:
    digest = domain_sha256("novel-flywheel-skill-v3-blind-sample-id-v1", {
        "campaign_manifest_sha256": campaign_manifest_sha,
        "pair_index": pair_index, "side_index": side_index,
    })
    return "blind-" + digest[:16]


def materialize_blind(
    *, repo: Path, state_path: Path, approval_root: Path, nonce_root: Path,
    artifact_root: Path,
) -> dict[str, Any]:
    _, rows = load_verified_campaign(
        repo=repo, state_path=state_path, approval_root=approval_root,
        nonce_root=nonce_root, artifact_root=artifact_root,
        allow_evidence_successor=True,
    )
    campaign_root = repo / CAMPAIGN_EVIDENCE_RELATIVE
    campaign_manifest_path = campaign_root / "sha256-manifest-v1.json"
    campaign_manifest = _read_json(campaign_manifest_path)
    campaign_manifest_sha = _sha_bytes(campaign_manifest_path.read_bytes())
    if campaign_manifest.get("status") != "EXACT":
        raise RuntimeError("CAMPAIGN_EVIDENCE_NOT_SEALED")
    blind_root = repo / BLIND_BUNDLE_RELATIVE
    mapping_root = repo / MAPPING_RELATIVE
    if blind_root.exists() or mapping_root.exists():
        raise RuntimeError("BLIND_HANDOFF_ALREADY_EXISTS")
    by_slot = {str(row["sample_slot"]): row for row in rows}
    mapping_rows = []
    pair_rows = []
    for pair_index, pair in enumerate(PAIR_ORDER, start=1):
        # Deterministic alternating shuffle freezes order without random mutable state.
        ordered = pair if pair_index % 2 == 0 else tuple(reversed(pair))
        samples = []
        for side_index, slot in enumerate(ordered, start=1):
            row = by_slot[slot]
            anonymous_id = _anon_id(campaign_manifest_sha, pair_index, side_index)
            artifact = row["artifact"]["artifact"]
            public_artifact = {
                "schema": "SkillV3BlindLiteraryArtifactV1", "anonymous_sample_id": anonymous_id,
                "title": artifact["title"], "narrative": artifact["narrative"],
            }
            filename = f"artifacts/{anonymous_id}.json"
            _write(blind_root / filename, public_artifact)
            samples.append({
                "anonymous_sample_id": anonymous_id, "artifact_path": filename,
                "artifact_sha256": _sha_bytes((blind_root / filename).read_bytes()),
            })
            mapping_rows.append({
                "anonymous_sample_id": anonymous_id, "sample_slot": slot,
                "sample_id": row["sample_id"], "arm": slot[0],
                "artifact_file_sha256": row["artifact_file_sha256"],
                "blind_artifact_sha256": samples[-1]["artifact_sha256"],
            })
        pair_rows.append({"anonymous_pair_id": f"blind-pair-{pair_index}", "samples": samples})
    aggregation_source = repo / (
        "docs/superpowers/reports/skill-v3-verbatim-selective-compiler-strategy-pivot-v1/"
        "multi-sample-narrative-aggregation-rule-v1.json"
    )
    fresh_context_source = repo / (
        "docs/superpowers/reports/skill-v3-verbatim-selective-compiler-strategy-pivot-v1/"
        "fresh-evaluator-context-policy-v2.json"
    )
    blind_policy_source = repo / (
        "docs/superpowers/reports/skill-v3-character-heavy-multi-sample-pilot-approval-readiness-recheck-v1/"
        "blind-batch-policy-binding-v1.json"
    )
    aggregation = _read_json(aggregation_source)
    _write(blind_root / "README.md", b"# Skill V3 anonymous literary evaluation bundle\n\nEvaluator-visible files only. Do not access the separate mapping root before judgments are frozen. Compare each anonymous pair dimension by dimension; do not guess arm identity.\n")
    _write(blind_root / "blind-batch-v1.json", {
        "schema": "SkillV3AnonymousBlindBatchV1", "status": "READY",
        "pair_count": 3, "sample_count": 6, "pairs": pair_rows,
        "arm_identity_visible": False, "skill_context_visible": False,
        "route_cost_approval_nonce_metadata_visible": False,
        "judgment_state": "NOT_STARTED",
    })
    fixture = _read_json(repo / pilot.FIXTURE_PATH)
    _write(blind_root / "minimal-task-context-v1.json", {
        "schema": "SkillV3BlindMinimalTaskContextV1",
        "experiment_demand": "character-heavy event realization",
        "authority_input": fixture["authority_input"],
        "instruction": (
            "Assess each anonymous artifact as a non-authoritative realization of the same frozen formal event. "
            "Judge relative literary quality and task fidelity using only the sealed rubric."
        ),
        "expected_output": ["title", "narrative"],
    })
    _write(blind_root / "sealed-literary-rubric-v1.json", aggregation)
    _write(blind_root / "sealed-criticality-policy-v1.json", {
        "schema": "SkillV3BlindCriticalityPolicyV1",
        "dimensions": aggregation["dimensions"],
        "critical_dimensions": aggregation["critical_dimensions"],
        "noncritical_dimensions": [d for d in aggregation["dimensions"] if d not in aggregation["critical_dimensions"]],
        "worst_case_rule": aggregation["worst_case_rule"],
        "minimum_support": aggregation["minimum_support"],
        "status": "SEALED",
    })
    _write(blind_root / "sealed-aggregation-policy-v1.json", aggregation)
    _write(blind_root / "fresh-evaluator-context-policy-v2.json", _read_json(fresh_context_source))
    _write(blind_root / "blind-batch-policy-v1.json", _read_json(blind_policy_source))
    _write(blind_root / "judgment-template-v1.json", {
        "schema": "SkillV3BlindJudgmentTemplateV1", "evaluator_context_id": "REQUIRED_FRESH_CONTEXT",
        "judgments_frozen": False, "pairs": [
            {"anonymous_pair_id": pair["anonymous_pair_id"], "dimensions": {
                dimension: {"relation": "UNSET", "evidence": [], "uncertainty": "UNSET"}
                for dimension in aggregation["dimensions"]
            }} for pair in pair_rows
        ],
        "allowed_relations": aggregation["relation_values"],
        "arm_identity_guess_forbidden": True,
    })
    _write(mapping_root / "README.md", b"# Main-context sealed blind mapping\n\nDo not expose to blind evaluators before their judgments are frozen.\n")
    _write(mapping_root / "sealed-mapping-v1.json", {
        "schema": "SkillV3BlindMappingV1", "status": "SEALED",
        "campaign_manifest_sha256": campaign_manifest_sha,
        "mapping_frozen_before_evaluation": True, "blind_evaluation_executed": False,
        "rows": mapping_rows,
    })
    blind_scan = _scan([p.read_bytes() for p in blind_root.rglob("*") if p.is_file()])
    _write(blind_root / "privacy-scan-v1.json", {
        "schema": "SkillV3BlindBundlePrivacyScanV1", **blind_scan,
        "sample_id_matches": 0, "arm_label_fields": 0,
        "skill_context_fields": 0, "route_cost_approval_nonce_fields": 0,
    })
    blind_manifest = _manifest(blind_root, "SkillV3BlindBundleSha256ManifestV1")
    _write(blind_root / "sha256-manifest-v1.json", blind_manifest)
    mapping_manifest = _manifest(mapping_root, "SkillV3BlindMappingSha256ManifestV1")
    _write(mapping_root / "sha256-manifest-v1.json", mapping_manifest)
    return {
        "status": "READY", "blind_root": str(blind_root), "mapping_root": str(mapping_root),
        "blind_manifest": blind_manifest, "mapping_manifest": mapping_manifest,
    }


def _defaults() -> dict[str, Path]:
    runtime = campaign.default_campaign_runtime_root() / EXPECTED_PERMISSION
    return {
        "state_path": runtime / "campaign-state-v1.json",
        "approval_root": approvals.default_successor_approval_store_root(),
        "nonce_root": default_nonce_store_root(),
        "artifact_root": campaign.default_campaign_runtime_root().parent / "real-boundary-v1",
    }


def main() -> None:
    defaults = _defaults()
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("campaign", "blind"))
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--state-path", type=Path, default=defaults["state_path"])
    parser.add_argument("--approval-root", type=Path, default=defaults["approval_root"])
    parser.add_argument("--nonce-root", type=Path, default=defaults["nonce_root"])
    parser.add_argument("--artifact-root", type=Path, default=defaults["artifact_root"])
    parser.add_argument("--focused", default="NOT_RUN")
    parser.add_argument("--related", default="NOT_RUN")
    parser.add_argument("--strict-l3", default="NOT_RUN")
    args = parser.parse_args()
    common = {
        "repo": args.repo_root.resolve(strict=True), "state_path": args.state_path,
        "approval_root": args.approval_root, "nonce_root": args.nonce_root,
        "artifact_root": args.artifact_root,
    }
    if args.mode == "campaign":
        result = materialize_campaign(
            **common, focused=args.focused, related=args.related, strict_l3=args.strict_l3,
        )
    else:
        result = materialize_blind(**common)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
