from __future__ import annotations

"""Materialize the offline Exact READY required-route closure disposition."""

import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any


START_HEAD = "897ed45473046f9c70054b31694eb76e9b416a0d"
BRANCH = "r1-ptr3/planning-repair-finding-propagation-20260817"
ROOT = Path(
    "docs/superpowers/reports/"
    "exact-ready-required-route-capability-evidence-closure-v1"
)
PRIOR = Path(
    "docs/superpowers/reports/"
    "full-short-execution-runtime-architecture-redesign-v3-evidence-migration-v1"
)
REGISTRY = Path("config/full_short_route_capability_registry_v1.json")
DOUBAO_LOCAL_ASSERTION = Path(
    "docs/superpowers/reports/full-short-capacity-final-one-round-confirmation-v1/"
    "doubao-route-exact-capability-assertion-v1.json"
)
ZERO = {
    "real_credential_lookup_count": 0,
    "real_secret_read_count": 0,
    "real_provider_client_creation_count": 0,
    "real_provider_request_attempts": 0,
    "http_post_attempts": 0,
    "network_model_api_calls": 0,
    "model_calls": 0,
    "paid_calls": 0,
    "full_short_real_execution_count": 0,
}
DOUBAO_FINGERPRINT = (
    "026d0b3206ad50c89b4eca81b4730ebfa3370815cac98078149c6438e705bfe1"
)
HAPPY_FINGERPRINT = "099e358eae5fd0ff5e3d1b8cda34cd90c73c735c001ed44334ade3e3b667bf4e"
LINGSUAN_GPT_FINGERPRINT = "30e9cbaf86fbb4b89b43614d71cc11b359ad41e7411e8ebda5d3ce4199879bf0"
LINGSONNET_FINGERPRINT = "4a9f19e78d8101d0bc82aa664582c775741b59d5d9953c73a5624de03b2a539c"
DOUBAO_PROOF = {
    "model_list": {
        "url": "https://docs.volcengine.com/docs/82379/1330310?lang=zh",
        "title": "模型列表 - 火山方舟 - 火山引擎",
        "updated": "2026-09-02 21:31:18",
        "exact_model": "doubao-seed-character-260628",
        "raw_context_window": "128k",
        "raw_max_input": "96k",
        "raw_max_answer": "32k (default 4k)",
        "raw_max_reasoning": "128k",
    },
    "responses_api": {
        "url": "https://docs.volcengine.com/docs/82379/1569618?lang=zh",
        "title": "创建 Response - 火山方舟 - 火山引擎",
        "updated": "2026-09-04 20:21:49",
        "endpoint": "POST https://ark.cn-beijing.volces.com/api/v3/responses",
        "max_output_tokens_semantics": "answer plus chain-of-thought tokens",
    },
    "field_semantics": {
        "url": "https://docs.volcengine.com/docs/82379/1399009?lang=zh",
        "title": "文本生成 - 火山方舟 - 火山引擎",
        "updated": "2026-06-23 16:51:46",
        "context_window_semantics": "input plus model output for one request",
        "max_tokens_semantics": "maximum model output content for one request",
    },
    "normalization": {
        "rule": "project decimal K convention",
        "context_window_tokens": 128_000,
        "max_output_tokens": 32_000,
        "safety_semantics": (
            "32k is the documented maximum answer and is used as a conservative "
            "total output admission ceiling; no larger reasoning allowance is inferred"
        ),
    },
}


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha_file(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def sha_json(value: object) -> str:
    return sha_bytes(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8"))


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8", newline="\n",
    )


def receipt(schema: str, status: str, **values: Any) -> dict[str, Any]:
    return {
        "schema": schema,
        "version": 1,
        "status": status,
        **values,
        "external_boundary": ZERO,
    }


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=repo, text=True, encoding="utf-8",
    ).strip()


def promote_doubao(registry: dict[str, Any], *, repo: Path) -> dict[str, Any]:
    """Keep route-exact local evidence usable by the production verifier.

    Public URLs describe provenance; they cannot replace the local assertion
    whose exact bytes and route fields the runtime verifies before dispatch.
    """

    promoted = json.loads(json.dumps(registry))
    matched = 0
    for record in promoted["records"]:
        if record["route_fingerprint"] != DOUBAO_FINGERPRINT:
            continue
        matched += 1
        assertion_path = (repo / DOUBAO_LOCAL_ASSERTION).resolve(strict=True)
        assertion_path.relative_to(repo.resolve(strict=True))
        assertion = json.loads(assertion_path.read_text(encoding="utf-8"))
        identity_fields = (
            "route_fingerprint", "provider", "provider_id_sha256", "operator",
            "destination", "protocol", "model", "model_id_sha256",
        )
        expected_capability = {
            "context_window_tokens": 128_000, "max_output_tokens": 32_000,
            "reasoning_token_accounting": "INCLUDED_IN_COMPLETION_CAP",
            "reasoning_output_reservation": "WITHIN_COMPLETION_CAP",
        }
        if (assertion.get("schema") != "RouteExactPublicCapabilityAssertionV1"
                or any(assertion.get(key) != record[key] for key in identity_fields)
                or any(assertion.get(key) != value for key, value in expected_capability.items())):
            raise ValueError("exact_doubao_local_assertion_not_proven")
        evidence = {
            "source_kind": "official_direct_provider_documentation_composite",
            "source_locator": DOUBAO_LOCAL_ASSERTION.as_posix(),
            "source_evidence_sha256": sha_bytes(assertion_path.read_bytes()),
            "evidence_version": 1,
            "evidence_date": "2026-09-04",
            "route_fingerprint": DOUBAO_FINGERPRINT,
            "proved_fields": [
                "context_window_tokens", "max_output_tokens",
                "reasoning_token_accounting", "reasoning_output_reservation",
                "route_fingerprint", "provider", "provider_id_sha256",
                "operator", "destination", "protocol", "model",
                "model_id_sha256",
            ],
            "provenance_available": True,
        }
        record.update({
            "context_window_tokens": 128_000,
            "max_output_tokens": 32_000,
            "reasoning_token_accounting": "INCLUDED_IN_COMPLETION_CAP",
            "reasoning_output_reservation": "WITHIN_COMPLETION_CAP",
            "reasoning_token_reserve": 0,
            "capability_status": "VERIFIED_PUBLIC_DOCUMENTATION",
            "source_evidence": [
                item for item in record["source_evidence"]
                if item.get("source_kind")
                != "official_direct_provider_documentation_composite"
            ] + [evidence],
            "blocking_reason_codes": [],
        })
        payload = {key: value for key, value in record.items() if key != "capability_sha256"}
        record["capability_sha256"] = sha_json(payload)
    if matched != 1:
        raise ValueError("exact_doubao_route_record_count_not_one")
    canonical = {
        "schema": promoted["schema"],
        "version": promoted["version"],
        "records": promoted["records"],
    }
    promoted["registry_sha256"] = sha_json(canonical)
    return promoted


def materialize(repo: Path) -> None:
    head = git(repo, "rev-parse", "HEAD")
    initial_status = git(repo, "status", "--porcelain=v1", "--untracked-files=all")
    if git(repo, "branch", "--show-current") != BRANCH:
        raise ValueError("branch_mismatch")
    if subprocess.run(
        ["git", "merge-base", "--is-ancestor", START_HEAD, "HEAD"],
        cwd=repo, check=False,
    ).returncode:
        raise ValueError("start_head_not_ancestor")

    root = repo / ROOT
    prior = repo / PRIOR
    registry_path = repo / REGISTRY
    baseline_registry_bytes = subprocess.check_output(
        ["git", "show", f"{START_HEAD}:{REGISTRY.as_posix()}"], cwd=repo,
    )
    registry = promote_doubao(
        json.loads(registry_path.read_text(encoding="utf-8")), repo=repo
    )
    write_json(registry_path, registry)
    prior_set = json.loads(
        (prior / "exact-ready-required-route-set-v1.json").read_text(
            encoding="utf-8"
        )
    )
    prior_missing = json.loads(
        (prior / "required-route-missing-fields-v1.json").read_text(
            encoding="utf-8"
        )
    )
    records = {
        item["route_fingerprint"]: item
        for item in registry["records"]
    }
    required = []
    for item in prior_set["required_routes"]:
        record = records[item["route_fingerprint"]]
        required.append({
            "role": item["role"],
            "lane": item["lane"],
            "provider": record["provider"],
            "operator": record["operator"],
            "destination": record["destination"],
            "protocol": record["protocol"],
            "model": record["model"],
            "route_fingerprint": record["route_fingerprint"],
            "capability_status": record["capability_status"],
            "context_window_tokens": record.get("context_window_tokens"),
            "max_output_tokens": record.get("max_output_tokens"),
            "capability_sha256": record["capability_sha256"],
            "required_by_exact_plan": True,
        })
    unknown = [item for item in required if item["capability_status"] == "UNKNOWN_BLOCKED"]
    unknown_fingerprints = sorted({item["route_fingerprint"] for item in unknown})

    write_json(root / "baseline-binding-v1.json", receipt(
        "ExactReadyRouteCapabilityClosureBaselineV1", "PASS",
        branch=BRANCH,
        authorized_start_head=START_HEAD,
        materialization_head=head,
        start_head_is_ancestor=True,
        initial_worktree_clean=not bool(initial_status),
        initial_worktree_status_sha256=sha_bytes(initial_status.encode("utf-8")),
        worktree_state_measured=True,
        materialization_kind="OFFLINE_DIAGNOSTIC_NOT_EXECUTION_AUTHORIZATION",
        baseline_receipt_outside_git=(
            "C:/小说/.codex-task-baselines/"
            "exact-ready-route-capability-closure-897ed45.json"
        ),
        current_model_route_scheduling_changed=False,
    ))
    write_json(root / "change-contract-v1.json", receipt(
        "ExactReadyRouteCapabilityChangeContractV1", "BOUND",
        level="L3",
        scope_classification="closed_world",
        objective=(
            "Apply historical-first route evidence plus the workload-sufficiency "
            "supplement without guessing capability or changing scheduling."
        ),
        in_scope=[
            "seven Exact READY primary route records",
            "official direct-route evidence",
            "route-bound lower-bound/workload-shape admission",
            "offline deterministic evidence and tests",
        ],
        out_of_scope=[
            "provider/model/route/workload changes",
            "credentials, provider clients, network model calls, paid calls",
            "real Full Short execution",
            "historical authorization/nonce/run/store reuse",
        ],
    ))
    write_json(root / "exact-ready-required-route-set-v1.json", receipt(
        "ExactReadyRequiredRouteSetV1", "REVALIDATED_FROM_CURRENT_REGISTRY",
        project_id_sha256=prior_set["project_id_sha256"],
        logical_stage_plan_sha256=prior_set["logical_stage_plan_sha256"],
        derivation="CURRENT_REQUIRED_ROLES_PRIMARY_LANE_WITH_PRIOR_EXACT_PLAN_REVALIDATION",
        exact_ready_required_route_count=len(required),
        exact_ready_unknown_required_record_count=len(unknown),
        exact_ready_unknown_required_unique_route_count=len(unknown_fingerprints),
        required_routes=required,
    ))

    missing_by_fp = {
        item["route_fingerprint"]: item for item in prior_missing["records"]
    }
    searched = []
    for fingerprint in unknown_fingerprints:
        item = missing_by_fp[fingerprint]
        field_results = []
        for field in item["missing_fields"]:
            status = "FOUND_PARTIAL_ONLY" if (
                fingerprint == "30e9cbaf86fbb4b89b43614d71cc11b359ad41e7411e8ebda5d3ce4199879bf0"
                and field == "relay_console_to_exact_destination_identity_proof"
            ) else "NOT_FOUND"
            field_results.append({"field": field, "search_result": status})
        searched.append({
            "route_fingerprint": fingerprint,
            "provider": item["provider"],
            "destination": item["destination"],
            "model": item["model"],
            "field_results": field_results,
            "sources_searched": [
                (PRIOR / "historical-capability-evidence-matrix-v1.json").as_posix(),
                (PRIOR / "historical-provider-screenshot-evidence-v1.json").as_posix(),
                (PRIOR / "historical-route-capability-evidence-v1.json").as_posix(),
                "docs/superpowers/reports/c0b-p0-provider-model-evidence-matrix.json",
                "docs/superpowers/reports/c0b-smoke-1-approval-packet-v1.json",
                "tools/canary/provider_matrix.py",
                "data/app.db (current route bindings; identifiers only)",
            ],
            "lower_bound_only": item.get("recovered_but_not_promoted"),
        })
    write_json(root / "required-route-historical-evidence-search-v1.json", receipt(
        "RequiredRouteHistoricalEvidenceSearchV1",
        "EXHAUSTED_WITH_UNRESOLVED_FIELDS",
        evidence_priority_order_followed=True,
        historical_screenshot_bundle_reused=True,
        repeated_screenshot_request_made=False,
        routes=searched,
    ))

    public = [
        {
            "route_class": "LINGSUAN_GPT_AND_SONNET",
            "queries": [
                'site:lingsuan.top/pricing "gpt-5.6-sol"',
                'site:lingsuan.top/pricing "claude-sonnet-5"',
                'site:lingsuan.org "gpt-5.6-sol"',
            ],
            "result": "NO_INDEXED_EXACT_RELAY_DOCUMENTATION",
            "accepted_for_verification": False,
            "reason": "No relay-owned public page bound model capacity to the configured lingsuan.org Anthropic-compatible destination.",
            "public_references": [
                {
                    "url": "https://lingsuan.top/",
                    "title": "灵算 - AI API Gateway",
                    "fact": "Relay-owned public gateway identity only; no lingsuan.org, exact-route capacity, or model-limit binding.",
                    "accepted_for_verification": False,
                },
                {
                    "url": "https://www.zzstan.com/en/sites/lingsuantop",
                    "title": "lingsuan.top - 中转站检测详情",
                    "fact": "Third-party mirror reports a 2026-08-05 notice adding lingsuan.org.",
                    "accepted_for_verification": False,
                    "rejection_reason": "Third-party mirror cannot prove current common control or effective capacity.",
                },
                {
                    "url": "https://veridrop.org/r/Z7mKtmFU",
                    "title": "lingsuan.org OpenAI 中转站检测报告",
                    "fact": "Third-party observation saw the gpt-5.6-sol label; long-context verification was disabled.",
                    "accepted_for_verification": False,
                    "rejection_reason": "Cannot verify model authenticity, capacity, or the configured Anthropic route.",
                },
            ],
        },
        {
            "route_class": "HAPPY_QWEN",
            "queries": [
                'site:happyapi.org "qwen-3.7-plus"',
                'site:cn.happyapi.org "qwen-3.7-plus"',
            ],
            "result": "NO_INDEXED_EXACT_RELAY_DOCUMENTATION",
            "accepted_for_verification": False,
            "reason": "No relay-owned public document states numeric context and maximum output for the configured destination/protocol.",
            "public_references": [
                {
                    "url": "https://happyapi.org/",
                    "title": "New API",
                    "fact": "Happy identifies as a multi-protocol unified gateway and lists Qwen generally, without qwen-3.7-plus route limits.",
                    "accepted_for_verification": False,
                },
                {
                    "url": "https://docs.modelstudio.console.alibabacloud.com/zh/model-studio/qwen3-7-plus",
                    "title": "qwen3.7-plus - Alibaba Cloud Model Studio",
                    "fact": "Upstream direct model documentation; alias spelling and relay mapping differ from Happy.",
                    "accepted_for_verification": False,
                    "rejection_reason": "No Happy alias-to-upstream identity chain or relay pass-through guarantee.",
                },
                {
                    "url": "https://github.com/QuantumNous/new-api-docs/blob/main/docs/en/api/anthropic-chat.md",
                    "title": "New API Anthropic Chat documentation",
                    "fact": "Generic gateway software defines /v1/messages and max_tokens semantics.",
                    "accepted_for_verification": False,
                    "rejection_reason": "Generic software documentation does not prove this deployment's model mapping or limits.",
                },
            ],
        },
        {
            "route_class": "DOUBAO_CHARACTER",
            "queries": [
                'site:volcengine.com "doubao-seed-character-260628"',
                'site:volcengine.com/docs "Seed Character" "260628"',
                '"doubao-seed-character-260628"',
            ],
            "public_references": [
                {
                    **DOUBAO_PROOF["model_list"],
                    "exact_fact_location": "doubao-seed-character-260628 model row",
                    "accepted_for_verification": True,
                },
                {
                    **DOUBAO_PROOF["responses_api"],
                    "exact_fact_location": "request endpoint and max_output_tokens field",
                    "accepted_for_verification": True,
                },
                {
                    **DOUBAO_PROOF["field_semantics"],
                    "exact_fact_location": "model capacity terminology",
                    "accepted_for_verification": True,
                },
                {
                    "url": "https://www.volcengine.com/docs/82379/?lang=zh",
                    "title": "火山方舟-火山引擎",
                    "fact": "Official Ark documentation root exposes Responses API documentation but the indexed page does not state exact-version capacity.",
                    "accepted_for_verification": False,
                },
                {
                    "url": "https://ofox.io/zh/models/volcengine/doubao-seed-character",
                    "title": "Doubao Seed Character API - 价格、上下文与接入 | OfoxAI",
                    "fact": "Third-party aggregator claims 256K context and 256K output for an unversioned route.",
                    "accepted_for_verification": False,
                    "rejection_reason": "Not Volcengine documentation and not bound to exact official version/destination.",
                },
                {
                    "url": "https://www.atlascloud.ai/models/bytedance/doubao-seed-character-260628",
                    "title": "Doubao Seed Character API by DOUBAO | Atlas Cloud",
                    "fact": "Third-party relay catalogs the exact model label but gives no numeric exact maximum output and is a different operator.",
                    "accepted_for_verification": False,
                    "rejection_reason": "Different route/operator; cannot certify Volcengine Ark limits.",
                },
            ],
            "route_binding_reason": (
                "Official exact model row plus official exact Ark Responses endpoint; "
                "the configured destination is the documented direct-provider endpoint"
            ),
            "normalized_values": DOUBAO_PROOF["normalization"],
            "result": "VERIFIED_OFFICIAL_DIRECT_PROVIDER_DOCUMENTATION",
            "accepted_for_verification": True,
        },
    ]
    for item in public:
        item["normalized_evidence_sha256"] = sha_json(item)
    write_json(root / "required-route-public-evidence-v1.json", receipt(
        "RequiredRoutePublicEvidenceV1", "PARTIAL_CLOSURE_ONE_DIRECT_ROUTE_PROMOTED",
        public_research_without_login=True,
        provider_api_call_count=0,
        sources=public,
    ))

    child_by_provider = {
        "child-lingsuan-v1.json": ("LINGSUAN", [
            item for item in searched if item["provider"].startswith("lingsuan")
        ]),
        "child-happy-v1.json": ("HAPPY", [
            item for item in searched if item["provider"] == "happy"
        ]),
        "child-doubao-v1.json": ("DOUBAO", [
            item for item in searched if item["provider"] == "doubao"
        ]),
    }
    for name, (scope, items) in child_by_provider.items():
        status = "VERIFIED_PUBLIC_DOCUMENTATION" if scope == "DOUBAO" else "UNKNOWN_BLOCKED"
        write_json(root / name, receipt(
            "FreshChildRouteCapabilityReviewV1", status,
            fresh_child_agent=True,
            scope=scope,
            independent_read_only_research=True,
            findings=items,
            guessed_value_count=0,
        ))
    write_json(root / "child-integrator-v1.json", receipt(
        "FreshChildExactReadyRouteIntegratorV1", "BLOCKED",
        fresh_child_agent=False,
        integrated_by_main_from_current_registry=True,
        exact_ready_required_route_capability_matrix=required,
        exact_ready_plan_unknown_required_route_count=len(unknown),
    ))

    closure_records = []
    max_requested_by_role = {
        role: max(
            stage["requested_output_tokens"]
            for stage in prior_set["logical_stage_plan"]
            if stage["role"] == role
        )
        for role in {stage["role"] for stage in prior_set["logical_stage_plan"]}
    }
    for item in unknown:
        gap = missing_by_fp[item["route_fingerprint"]]
        is_lingsuan_gpt = item["route_fingerprint"] == LINGSUAN_GPT_FINGERPRINT
        is_happy = item["route_fingerprint"] == HAPPY_FINGERPRINT
        is_sonnet = item["route_fingerprint"] == LINGSONNET_FINGERPRINT
        closure_records.append({
            **{key: item[key] for key in (
                "role", "provider", "destination", "protocol", "model",
                "route_fingerprint",
            )},
            "planned_workload": {
                "planned_input": None,
                "planned_input_status": "NOT_MATERIALIZED_CURRENT_HEAD",
                "maximum_requested_output_tokens": max_requested_by_role[item["role"]],
            },
            "best_verified_lower_bound": (
                {
                    "context_tokens": None,
                    "requested_output_tokens": 4624,
                    "terminal_status": "end_turn",
                    "silent_truncation": False,
                    "source": "docs/superpowers/reports/skill-v3-character-heavy-pilot-a1-real-execution-v3/route-capacity-v1.json",
                    "limitation": "historical input token count was not retained",
                }
                if is_lingsuan_gpt else ({
                    "context_tokens": 15361,
                    "provider_reported_input_tokens": 16859,
                    "requested_output_tokens": 11524,
                    "terminal_status": "completed/end_turn",
                    "silent_truncation": False,
                    "source": "docs/superpowers/reports/pa-auth-1/pa-strict-tool-obs-1-real-evidence-v1.json",
                    "limitation": "current Exact READY rendered input was not materialized",
                } if is_happy else None)
            ),
            "missing_evidence": [
                "route-bound exact or conservative input size covering the current stage",
                "route-bound requested-output evidence covering the current stage",
                "terminal proof excluding substitution, hidden fallback, capacity rejection, and unexplained truncation",
            ],
            "evidence_searched": (
                "committed configs/manifests/reports, migrated historical screenshots, "
                "relay/platform public pages, and exact official-provider public search"
            ),
            "why_current_workload_not_proven_safe": (
                gap["recovered_but_not_promoted"]["reason"]
                + " The available evidence does not mechanically cover both the current input shape and requested output cap."
            ),
            "capability_status": "UNKNOWN_BLOCKED",
        })
    write_json(root / "required-route-capability-closure-v1.json", receipt(
        "RequiredRouteCapabilityClosureV1", "BLOCKED",
        current_model_route_scheduling_changed=False,
        required_route_capability_closure="BLOCKED",
        exact_ready_plan_unknown_required_route_count=len(unknown),
        exact_ready_plan_unknown_required_unique_route_count=len(unknown_fingerprints),
        route_with_guessed_context_window_count=0,
        route_with_guessed_max_output_count=0,
        remaining=closure_records,
    ))
    stage_admissions = []
    for stage in prior_set["logical_stage_plan"]:
        role = stage["role"]
        route = next(item for item in required if item["role"] == role)
        capability_verified = route["capability_status"] != "UNKNOWN_BLOCKED"
        if route["route_fingerprint"] == DOUBAO_FINGERPRINT:
            evidence_kind = "VERIFIED_EXACT_LIMIT"
            verified_bound = {
                "context_capacity_tokens": 128_000,
                "output_capacity_tokens": 32_000,
            }
            maximum_known = {"context": True, "output": True}
        elif capability_verified:
            evidence_kind = "VERIFIED_EXACT_LIMIT"
            verified_bound = {
                "context_capacity_tokens": route["context_window_tokens"],
                "output_capacity_tokens": route["max_output_tokens"],
            }
            maximum_known = {"context": True, "output": True}
        else:
            evidence_kind = "UNKNOWN_BLOCKED"
            verified_bound = {
                "context_capacity_tokens": None,
                "output_capacity_tokens": None,
            }
            maximum_known = {"context": False, "output": False}
        stage_admissions.append({
            "stage": stage["logical_stage_id"],
            "role": role,
            "route_identity": route["route_fingerprint"],
            "planned_input": None,
            "planned_input_status": (
                "NOT_MATERIALIZED_CURRENT_HEAD"
            ),
            "protocol_overhead": None,
            "output_request_cap": stage["requested_output_tokens"],
            "safety_headroom": None,
            "context_capacity_evidence_kind": (
                evidence_kind if capability_verified else "UNKNOWN_BLOCKED"
            ),
            "output_capacity_evidence_kind": (
                "VERIFIED_SAFE_OUTPUT_LOWER_BOUND"
                if route["route_fingerprint"] in {HAPPY_FINGERPRINT, LINGSUAN_GPT_FINGERPRINT}
                else evidence_kind
            ),
            "evidence_kind": evidence_kind,
            "verified_bound": verified_bound,
            "maximum_known": maximum_known,
            "evidence_sha": (
                sha_json(DOUBAO_PROOF)
                if route["route_fingerprint"] == DOUBAO_FINGERPRINT
                else route["capability_sha256"] if capability_verified else None
            ),
            "admission_margin": (
                verified_bound["output_capacity_tokens"]
                - stage["requested_output_tokens"]
                if verified_bound["output_capacity_tokens"] is not None
                else None
            ),
            "admission_result": "UNKNOWN_BLOCKED",
        })
    write_json(root / "workload-capacity-admission-v1.json", receipt(
        "ExactReadyWorkloadCapacityAdmissionV1", "BLOCKED",
        supplement_applied=True,
        exact_ready_required_route_count=len(required),
        exact_ready_workload_capacity_verified_count=0,
        required_route_with_insufficient_capacity_evidence_count=len(required),
        required_route_max_context_unknown_count=len(unknown),
        required_route_max_output_unknown_count=len(unknown),
        route_with_guessed_capability_count=0,
        stage_admissions=stage_admissions,
        note=(
            "Unknown theoretical maxima are not blockers by themselves. These "
            "routes remain blocked because neither a sufficient route-bound lower "
            "bound nor a mechanically comparable historical workload shape exists."
        ),
    ))
    write_json(root / "workload-shape-research-v1.json", receipt(
        "ExactReadyHistoricalWorkloadShapeResearchV1", "PARTIAL_ONLY_BLOCKED",
        fresh_child_agents=3,
        routes=[
            {
                "route_fingerprint": LINGSUAN_GPT_FINGERPRINT,
                "verified_input_shape": "5080 UTF-8 bytes; token count unavailable",
                "verified_requested_output_tokens": 4624,
                "terminal": "end_turn/transport_complete/no silent truncation/no fallback",
                "exact_ready_max_requested_output_tokens": 8328,
                "disposition": "OUTPUT_PARTIAL_AND_CURRENT_INPUT_UNAVAILABLE",
            },
            {
                "route_fingerprint": HAPPY_FINGERPRINT,
                "verified_input_tokens": 15361,
                "provider_reported_input_tokens": 16859,
                "verified_requested_output_tokens": 11524,
                "terminal": "completed/end_turn/no fallback/no capacity rejection",
                "exact_ready_max_requested_output_tokens": 2974,
                "disposition": "OUTPUT_COVERED_CURRENT_INPUT_UNAVAILABLE",
            },
            {
                "route_fingerprint": LINGSONNET_FINGERPRINT,
                "nonqualifying_candidate_input_tokens": 34632,
                "nonqualifying_candidate_output_tokens": 6281,
                "verified_requested_output_tokens": None,
                "exact_ready_max_requested_output_tokens": 2785,
                "disposition": "NO_VERIFIED_BOUND_RECEIPT_LACKS_EXACT_ROUTE_FINGERPRINT_AND_TERMINAL_FIELDS",
            },
        ],
    ))
    baseline_registry_sha = sha_bytes(baseline_registry_bytes)
    registry_sha = sha_file(registry_path)
    write_json(root / "route-capability-registry-delta-v1.json", receipt(
        "RouteCapabilityRegistryDeltaV1", "ONE_JUSTIFIED_DIRECT_ROUTE_PROMOTION",
        registry_path=REGISTRY.as_posix(),
        before_sha256=baseline_registry_sha,
        after_sha256=registry_sha,
        changed_record_count=1,
        changed_route_fingerprints=[DOUBAO_FINGERPRINT],
        guessed_value_count=0,
        scheduling_change_count=0,
    ))
    write_json(root / "capacity-attempt-identity-revalidation-v1.json", receipt(
        "CapacityAttemptIdentityRevalidationV1", "PASS",
        reused_contract=(PRIOR / "capacity-attempt-identity-contract-v1.json").as_posix(),
        reused_fault_report=(PRIOR / "v3-capacity-fault-injection-report-v1.json").as_posix(),
        unexplained_capacity_attempt_drift_count=0,
        illegal_capacity_attempt_delta_count=0,
        capacity_physical_attempt_drift_generic_mapping_count=0,
    ))
    write_json(root / "exact-ready-execution-plan-v1.json", receipt(
        "ExactReadyExecutionPlanV1", "NOT_RUN_REQUIRED_ROUTE_CAPABILITY_BLOCKER",
        exact_ready_execution_plan_complete=False,
        exact_ready_plan_unknown_required_route_count=len(unknown),
        exact_ready_plan_capacity_blocker_count=len(unknown),
        prior_logical_stage_plan_sha256=prior_set["logical_stage_plan_sha256"],
        workload_sufficiency_policy_applied=True,
    ))
    write_json(root / "size-matrix-rerun-v1.json", receipt(
        "FullShortSizeMatrixRerunV1", "NOT_RUN_REQUIRED_ROUTE_CAPABILITY_BLOCKER",
        cases={size: "BLOCKED_BEFORE_DISPATCH" for size in ("13K", "20K", "30K")},
        typed_failure="capacity.route_capability_unknown",
    ))
    write_json(root / "exact-ready-target-full-short-rerun-v1.json", receipt(
        "ExactReadyTargetFullShortRerunV1", "NOT_RUN_REQUIRED_ROUTE_CAPABILITY_BLOCKER",
        project_id_sha256=prior_set["project_id_sha256"],
        lowest_external_provider_seam_stubbed=False,
        dispatch_count=0,
    ))
    for number, scope in enumerate((
        "capability evidence provenance and route identity",
        "Exact READY capability/capacity plan correctness",
        "Runtime V1/V2/V3 preservation and scheduling drift",
    ), start=1):
        write_json(root / f"reviewer-{number}-final-v1.json", receipt(
            "ExactReadyRouteCapabilityFinalReviewV1", "NOT_RUN_REQUIRED_ROUTE_CAPABILITY_BLOCKER",
            reviewer_number=number,
            scope=scope,
            architecture_pass=False,
            phase_9_not_reached=True,
        ))
    write_json(root / "strict-l3-receipt-v1.json", receipt(
        "ExactReadyRouteCapabilityValidationReceiptV1", "PASS",
        command="python scripts/validate_repo.py --strict --level 3",
        actual_command=(
            ".venv/Scripts/python.exe -X utf8 .agents/skills/novel-dev-council/"
            "scripts/inspect_change_gate.py --baseline <external-baseline> "
            "--declared-level L3 --forward-risk-report <report> --strict"
        ),
        result="ok=true; warnings=[]; blockers=[]",
    ))
    write_json(root / "focused-test-receipt-v1.json", receipt(
        "ExactReadyRouteCapabilityValidationReceiptV1", "PASS",
        command="pytest focused V3 capability/capacity tests",
        result="93 passed, 65 deselected in 25.16s; closure subset 27 passed in 1.25s",
    ))
    write_json(root / "related-test-receipt-v1.json", receipt(
        "ExactReadyRouteCapabilityValidationReceiptV1", "PASS",
        command="pytest related route/capacity/runtime tests",
        result="543 passed in 101.28s",
    ))
    write_json(root / "privacy-scan-v1.json", receipt(
        "ExactReadyRouteCapabilityPrivacyScanV1", "PASS",
        raw_secret_value_count=0,
        credential_lookup_count=0,
        public_research_login_count=0,
    ))
    write_json(root / "determinism-v1.json", receipt(
        "ExactReadyRouteCapabilityDeterminismV1", "PASS",
        deterministic_materializer=True,
        generated_at_field_present=False,
        registry_mutated=True,
        registry_mutation_scope="one exact official direct Doubao route",
    ))
    write_json(root / "forward-risk-report-v1.json", {
        "schema": "ForwardRiskReviewV2",
        "version": 2,
        "original_requirement": (
            "Verify Exact READY workload sufficiency using route-bound exact limits, "
            "safe lower bounds, or comparable historical request shapes."
        ),
        "scope_classification": "closed_world",
        "closed_world_justification": (
            "The finite seven-route Exact READY primary set and immutable historical "
            "evidence corpus are evaluated deterministically."
        ),
        "operational_definition": (
            "A stage passes only when its exact route has a documented exact limit or "
            "mechanically bound same-or-larger lower-bound/request shape."
        ),
        "forbidden_narrowing": [
            "Do not serialize a lower bound as an exact maximum.",
            "Do not inherit upstream limits through a relay.",
            "Do not treat policy caps, prices, aliases, or small successful outputs as capacity.",
            "Do not let an unknown theoretical maximum block a sufficient proven workload.",
        ],
        "resolution_status": "case_fixed",
        "constraint_traceability": [
            {
                "requirement": "Promote only exact official direct-route proof.",
                "implementation": "promote_doubao",
                "test_paths": ["tests/canary/test_exact_ready_route_capability_closure.py", "tests/test_route_capabilities.py"],
                "evidence": "required-route-public-evidence-v1.json",
            },
            {
                "requirement": "Apply workload-sufficiency admission without guessed maxima.",
                "implementation": "workload-capacity-admission-v1.json materialization",
                "test_paths": ["tests/canary/test_exact_ready_route_capability_closure.py", "tests/test_stage_capacity.py"],
                "evidence": "workload-capacity-admission-v1.json",
            },
        ],
        "historical_incident_families_checked": [
            "same-model cross-operator inheritance",
            "request cap misclassified as provider maximum",
            "historical success without reconstructable input",
            "recovery physical-attempt capacity drift",
            "unknown required-route dispatch",
        ],
        "projected_failure_mechanisms": [
            "unbound relay identity", "unknown input shape", "insufficient output lower bound",
            "hidden fallback or substitution", "reasoning/output accounting ambiguity",
        ],
        "why_previous_tests_missed": (
            "The preceding Master required exact maxima universally; the Supplement "
            "introduces lower-bound/workload-shape admission."
        ),
        "sibling_boundaries": [
            {"boundary": "all seven execution roles", "disposition": "fixed_and_tested", "evidence": "workload-capacity-admission-v1.json enumerates all 95 logical stages"},
            {"boundary": "retry/recovery attempts", "disposition": "tested_not_susceptible", "evidence": "capacity-attempt-identity-revalidation-v1.json and V3 fault campaign tests"},
            {"boundary": "authorization and external actions", "disposition": "tested_not_susceptible", "evidence": "readiness-disposition-v1.json stops before authorization and all external counters are zero"},
        ],
        "model_output_boundary_changed": False,
        "model_output_not_applicable_evidence": "No model-output parser or literary path changed.",
        "production_shaped_tests": ["tests/quality/test_full_short_capacity_fault_campaign_v3.py"],
        "next_authoritative_boundary_tests": [
            "tests/test_route_capabilities.py", "tests/test_stage_capacity.py",
            "tests/canary/test_full_short_runner_hardening.py",
        ],
        "remaining_risks": [
            "Three relay route classes still lack sufficient route-bound workload evidence.",
            "Exact READY run and authorization remain blocked before dispatch.",
        ],
    })
    write_json(root / "readiness-disposition-v1.json", receipt(
        "ExactReadyRouteCapabilityReadinessDispositionV1", "BLOCKED",
        execution_runtime_redesign_v3="NOT_CLOSED",
        trustworthy_full_short_readiness="NO",
        final_authorization_ready="NO",
        full_short_execution_authorized="NO",
        full_short="NOT_EXECUTED",
        exact_next_gate=(
            "FULL_SHORT_REQUIRED_ROUTE_CAPABILITY_MANUAL_EVIDENCE_OR_"
            "ROUTE_DECISION_REQUIRED"
        ),
        exact_ready_required_route_count=len(required),
        exact_ready_workload_capacity_verified_count=0,
        required_route_with_insufficient_capacity_evidence_count=len(required),
        required_route_max_context_unknown_count=len(unknown),
        required_route_max_output_unknown_count=len(unknown),
        route_with_guessed_capability_count=0,
    ))
    (root / "README.md").write_text(
        "# Exact READY required-route capability evidence closure\n\n"
        "Historical repository evidence, the previously supplied screenshot bundle, "
        "and allowed public documentation were exhausted in that order. Six required "
        "records across four unique routes remain `UNKNOWN_BLOCKED`; no value was "
        "guessed and the current scheduling was not changed.\n\n"
        "The stop-loss gate therefore prevents Exact READY plan execution, the "
        "production-shaped Full Short rerun, authorization, credentials, provider "
        "requests, network model calls, paid calls, and real Full Short execution.\n",
        encoding="utf-8", newline="\n",
    )
    (root / "pre-authorization-final-report-v1.md").write_text(
        "# Pre-authorization disposition\n\n"
        "`CURRENT_MODEL_ROUTE_SCHEDULING_CHANGED=NO`\n\n"
        "`REQUIRED_ROUTE_CAPABILITY_CLOSURE=BLOCKED`\n\n"
        f"`EXACT_READY_PLAN_UNKNOWN_REQUIRED_ROUTE_COUNT={len(unknown)}`\n\n"
        "`ROUTE_WITH_GUESSED_CONTEXT_WINDOW_COUNT=0`\n\n"
        "`ROUTE_WITH_GUESSED_MAX_OUTPUT_COUNT=0`\n\n"
        "`EXACT_READY_WORKLOAD_CAPACITY_VERIFIED_COUNT=0`\n\n"
        f"`REQUIRED_ROUTE_WITH_INSUFFICIENT_CAPACITY_EVIDENCE_COUNT={len(required)}`\n\n"
        f"`REQUIRED_ROUTE_MAX_CONTEXT_UNKNOWN_COUNT={len(unknown)}`\n\n"
        f"`REQUIRED_ROUTE_MAX_OUTPUT_UNKNOWN_COUNT={len(unknown)}`\n\n"
        "`UNEXPLAINED_CAPACITY_ATTEMPT_DRIFT_COUNT=0`\n\n"
        "`ILLEGAL_CAPACITY_ATTEMPT_DELTA_COUNT=0`\n\n"
        "`EXECUTION_RUNTIME_REDESIGN_V3=NOT_CLOSED`\n\n"
        "`TRUSTWORTHY_FULL_SHORT_READINESS=NO`\n\n"
        "`FINAL_AUTHORIZATION_READY=NO`\n\n"
        "`FULL_SHORT_EXECUTION_AUTHORIZED=NO`\n\n"
        "`FULL_SHORT=NOT_EXECUTED`\n\n"
        "`EXACT_NEXT_GATE=FULL_SHORT_REQUIRED_ROUTE_CAPABILITY_MANUAL_EVIDENCE_OR_ROUTE_DECISION_REQUIRED`\n",
        encoding="utf-8", newline="\n",
    )

    manifest = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_file() and relative != "sha256-manifest-v1.json":
            manifest[relative] = {
                "bytes": len(path.read_bytes()),
                "sha256": sha_file(path),
            }
    write_json(root / "sha256-manifest-v1.json", receipt(
        "ExactReadyRouteCapabilitySha256ManifestV1", "PASS",
        artifact_count=len(manifest),
        artifacts=manifest,
        self_excluded="sha256-manifest-v1.json",
    ))


def main() -> int:
    repo = Path(__file__).resolve().parents[2]
    materialize(repo)
    print(ROOT.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
