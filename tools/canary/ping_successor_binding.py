"""Read-only source revalidation for the bounded ping successor controller."""
from __future__ import annotations

import ast
import base64
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from novel_flywheel.ping_successor import (
    PING_EVIDENCE_ROOT, HistoricalAdmissionManifest, PingRecoveryProofs,
    ERROR_HARDENING_EVIDENCE_ROOT, ERROR_HARDENING_SOURCE_SHA256, ErrorHardeningRecoveryProofs,
)


class PingSuccessorBindingError(ValueError):
    pass


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise PingSuccessorBindingError(code)


def _raw(root: Path, relative: str, digest: str | None = None) -> bytes:
    path = (root / relative).resolve(strict=True)
    _require(path.is_relative_to(root.resolve(strict=True)), "PING_PROOF_PATH_ESCAPE")
    raw = path.read_bytes()
    _require(digest is None or hashlib.sha256(raw).hexdigest() == digest, "PING_PROOF_SOURCE_HASH_DRIFT")
    return raw


def build_ping_recovery_binding(repo: Path, cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate physical proof bytes and their meaning, then bind their hashes."""
    try:
        return _build(repo, cases)
    except (OSError, KeyError, TypeError, ValueError, StopIteration) as exc:
        if isinstance(exc, PingSuccessorBindingError):
            raise
        raise PingSuccessorBindingError("PING_PROOF_MISSING_OR_INVALID") from None


def _build(repo: Path, cases: list[dict[str, Any]]) -> dict[str, Any]:
    names = {
        "authoritative_ping_semantics": "authoritative-ping-semantics-v1.json",
        "exact_replay": "probe02-exact-replay-after-fix-v1.json",
        "workload_disposition": "probe02-workload-evidence-disposition-v1.json",
        "request_zero_diff": "shared-protocol-request-zero-diff-v1.json",
        "response_regression_matrix": "shared-protocol-response-regression-matrix-v1.json",
        "historical_admission_manifest": "historical-workload-admission-v1.json",
    }
    binding, documents = {}, {}
    for field, filename in names.items():
        relative = f"{PING_EVIDENCE_ROOT}/{filename}"
        raw = _raw(repo, relative)
        binding[field] = {"identity": relative, "sha256": hashlib.sha256(raw).hexdigest()}
        documents[field] = json.loads(raw)
    official, replay, request, matrix, disposition = (documents[k] for k in (
        "authoritative_ping_semantics", "exact_replay", "request_zero_diff",
        "response_regression_matrix", "workload_disposition"))
    _require(official.get("SEMANTIC_MESSAGE_TERMINAL_EVENT") == "message_stop"
        and official.get("POST_MESSAGE_STOP_PING_COMPATIBILITY_INFERENCE") == "SUPPORTED"
        and bool(official.get("AUTHORITATIVE_SOURCE_REFERENCES")), "PING_PROTOCOL_GATE_NOT_PASS")
    _require(request.get("status") == "PASS" and all(type(request.get(k)) is int and request[k] == 0
        for k in ("OUTBOUND_REQUEST_BODY_CHANGED_COUNT", "MODEL_VISIBLE_REQUEST_BYTES_CHANGED_COUNT",
            "ROUTE_BINDING_CHANGED_COUNT", "OUTPUT_CAP_CHANGED_COUNT", "REASONING_POLICY_CHANGED_COUNT",
            "REQUEST_BUILDER_SOURCE_DIFF")), "PING_REQUEST_ZERO_DIFF_NOT_PASS")
    inventory = request["inventory"]
    inventory_raw = (json.dumps(inventory, ensure_ascii=False, indent=2) + "\n").encode()
    _require(hashlib.sha256(inventory_raw).hexdigest() == request["before_inventory_sha256"]
        == request["after_inventory_sha256"] and request["request_count"] >= 1
        and len(inventory["request_rows"]) == request["request_count"], "PING_REQUEST_INVENTORY_DRIFT")
    required_sources = {"src/novel_flywheel/provider_payloads.py", "src/novel_flywheel/providers/http.py",
        "src/novel_flywheel/providers/registry.py", "src/novel_flywheel/context_policy.py"}
    _require(set(inventory["source_hashes"]) == required_sources, "PING_REQUEST_SOURCE_SET_DRIFT")
    for path, digest in inventory["source_hashes"].items():
        _raw(repo, path, digest)
    tree = ast.parse(_raw(repo, "src/novel_flywheel/providers/anthropic.py").decode("utf-8"))
    complete = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "complete")
    prefix = ast.dump(ast.Module(body=complete.body[:5], type_ignores=[]), include_attributes=False)
    _require(hashlib.sha256(prefix.encode()).hexdigest() == inventory["complete_request_prefix_ast_sha256"],
        "PING_REQUEST_SOURCE_DRIFT")
    _require(matrix.get("status") == "PASS" and type(matrix.get("SHARED_PROTOCOL_REGRESSION_COUNT")) is int
        and matrix["SHARED_PROTOCOL_REGRESSION_COUNT"] == 0 and len(matrix.get("cases", [])) >= 13
        and all(c.get("status") == "PASS" for c in matrix["cases"]), "PING_RESPONSE_REGRESSION_NOT_PASS")
    manifest, terminal = _validate_historical_sources(repo, cases, documents["historical_admission_manifest"])
    chosen = disposition.get("PROBE02_HISTORICAL_EVIDENCE_DISPOSITION")
    _require(chosen in {"REPLAY_PROVEN_PASS", "FRESH_REPLACEMENT_REQUIRED"}, "PING_DISPOSITION_UNRESOLVED")
    if chosen == "REPLAY_PROVEN_PASS":
        _require(replay.get("PROBE02_EXACT_REPLAY_AFTER_FIX") == "PASS"
            and replay.get("POST_TERMINAL_PING_COUNT") == 3
            and replay.get("POST_TERMINAL_PING_IGNORED_COUNT") == 3
            and replay.get("http_status") == 200 and replay.get("transport_complete") is True
            and disposition.get("original_http_acceptance_proven") is True
            and disposition.get("exact_replay_proof_sha256") == binding["exact_replay"]["sha256"],
            "PING_REPLAY_NOT_PROVEN")
        p = manifest.historical_cases[-1]
        _require(replay.get("canonical_input_tokens") == p.canonical_input_tokens
            and replay.get("canonical_output_tokens") == p.canonical_output_tokens, "PING_REPLAY_USAGE_DRIFT")
    _require(set(replay["source_hashes"]) == {"src/novel_flywheel/providers/anthropic.py",
        "src/novel_flywheel/provider_response_capture.py"}, "PING_REPLAY_SOURCE_SET_DRIFT")
    for path, digest in replay["source_hashes"].items():
        _raw(repo, path, digest)
    binding.update(raw_capture_sha256=replay["raw_capture_sha256"], probe02_disposition=chosen,
        excluded_prior_nonce_sha256s=[r["nonce_sha256"] for r in terminal["records"][:2]],
        selected_probe_ordinals=list(range(3 if chosen == "REPLAY_PROVEN_PASS" else 2, 9)),
        historical_cases=[p.model_dump(mode="json") for p in manifest.historical_cases])
    return PingRecoveryProofs.model_validate(binding).model_dump(mode="json")


def _validate_historical_sources(repo: Path, cases: list[dict[str, Any]], manifest_document: Mapping[str, Any]):
    manifest = HistoricalAdmissionManifest.model_validate(manifest_document)
    history_root = repo.resolve().parent / manifest.source_root_identity
    _raw(history_root, "final-manifest-v1.json", manifest.source_manifest_sha256)
    old_authorization_raw = _raw(history_root, "campaign/campaign-authorization-v1.json")
    old_authorization = json.loads(old_authorization_raw)
    _require(old_authorization["probe_campaign"]["cases"] == cases, "PING_HISTORICAL_REQUEST_FIXTURE_ROUTE_DRIFT")
    terminal = json.loads(_raw(history_root, "campaign/probe-terminal-state-v1.json"))
    _require([r["ordinal"] for r in terminal["records"]] == list(range(1, 9)), "PING_HISTORICAL_LEDGER_INVALID")
    _require(all(r["state"] == "UNUSED" and r["nonce_sha256"] is None for r in terminal["records"][2:]),
        "PING_REQUIRED_CASE_ALREADY_DISPATCHED")
    for p in manifest.historical_cases:
        ordinal = 1 if p.case_id == "full-short-probe-01-draft_plain" else 2
        expected_files = {"campaign/campaign-authorization-v1.json", "campaign/probe-terminal-state-v1.json",
            f"campaign/probe-capture-metadata-{ordinal:02d}.json"}
        if ordinal == 1:
            expected_files.add("campaign/probe-evidence-01.json")
        _require(set(p.source_files) == expected_files, "PING_HISTORICAL_SOURCE_SET_DRIFT")
        loaded = {}
        for key, reference in p.source_files.items():
            _require(key == reference.identity, "PING_HISTORICAL_SOURCE_IDENTITY_DRIFT")
            loaded[key] = _raw(history_root, reference.identity, reference.sha256)
        record = terminal["records"][ordinal - 1]
        case = cases[ordinal - 1]
        metadata_raw = loaded[f"campaign/probe-capture-metadata-{ordinal:02d}.json"]
        metadata = json.loads(metadata_raw)["metadata"]
        capture = base64.b64decode(record["raw_response_base64"], validate=True)
        _require(hashlib.sha256(old_authorization_raw).hexdigest() == p.source_authorization_sha256
            and old_authorization["frozen_execution"]["final_execution_head"] == p.source_execution_head
            and hashlib.sha256(capture).hexdigest() == p.source_capture_sha256 == record["raw_response_sha256"]
            and hashlib.sha256(metadata_raw).hexdigest() == p.source_capture_metadata_sha256
            and record["nonce_sha256"] == p.source_nonce_sha256 == metadata["nonce_sha256"]
            and record["case_id"] == p.case_id and record["case_sha256"] == case["case_sha256"]
            and metadata["request_sha256"] == p.source_request_sha256 == case["request_sha256"]
            and metadata["case_sha256"] == case["case_sha256"]
            and metadata["authorization_sha256"] == p.source_authorization_sha256
            and metadata["execution_head"] == p.source_execution_head
            and metadata["provider_entity_sha256"] == p.source_capture_sha256
            and metadata["provider_entity_bytes"] == len(capture)
            and metadata["route_fingerprint"] == case["route"]["route_fingerprint"]
            and metadata["status_code"] == 200 and metadata["transport_complete"] is True,
            "PING_HISTORICAL_ACCEPTANCE_BINDING_DRIFT")
        evidence_path = "campaign/probe-evidence-01.json" if ordinal == 1 else "campaign/probe-terminal-state-v1.json"
        _require(hashlib.sha256(loaded[evidence_path]).hexdigest() == p.source_evidence_sha256,
            "PING_HISTORICAL_EVIDENCE_HASH_DRIFT")
        if ordinal == 1:
            original = json.loads(loaded[evidence_path])["payload"]
            result = original["result"]
            _require(record["state"] == "PASS_CONSUMED" and original["nonce"]["dispatch_attempt_count"] == 1
                and original["nonce"]["state"] == "CONSUMED" and original["nonce"]["nonce_sha256"] == p.source_nonce_sha256
                and result["terminal_status"] == "SUCCESS" and result["complete"] is True
                and result["input_accepted"] is True and result["output_accepted"] is True
                and result["actual_input_tokens"] == p.canonical_input_tokens
                and result["actual_output_tokens"] == p.canonical_output_tokens,
                "PING_HISTORICAL_PASS_NOT_PROVEN")
    return manifest, terminal


ERROR_PROOF_FILES = {
    "authoritative_error_semantics": "authoritative-error-event-semantics-v1.json",
    "authoritative_ping_semantics": "authoritative-ping-semantics-v1.json",
    "error_precedence_contract": "error-precedence-contract-v1.json",
    "nonobject_error_normalization": "nonobject-error-normalization-contract-v1.json",
    "probe01_exact_replay": "probe01-exact-replay-after-fix-v1.json",
    "probe02_exact_replay": "probe02-exact-replay-after-fix-v1.json",
    "request_zero_diff": "shared-request-zero-diff-v1.json",
    "response_regression_matrix": "shared-response-regression-matrix-v1.json",
    "historical_admission_manifest": "historical-workload-admission-v1.json",
    "historical_source_authentication": "historical-source-authentication-v1.json",
}
ERROR_REVIEW_SOURCE_PATHS = frozenset({
    "src/novel_flywheel/providers/anthropic.py",
    "src/novel_flywheel/providers/http.py",
    "src/novel_flywheel/provider_response_capture.py",
    "src/novel_flywheel/ping_successor.py",
    "src/novel_flywheel/full_short_campaign_authorization.py",
    "src/novel_flywheel/external_workload_evidence.py",
    "src/novel_flywheel/full_short_probe_campaign.py",
    "tools/canary/ping_successor_binding.py",
    "tools/canary/execute_full_short_budget_unblocked_one_round.py",
})


def _current_sources(repo: Path, sources: Mapping[str, Any], *, required=()) -> None:
    _require(isinstance(sources, dict) and bool(sources) and set(required).issubset(sources),
        "ERROR_PROOF_SOURCE_SET_INVALID")
    for relative, digest in sources.items():
        _raw(repo, relative, digest)


def _function_ast(repo: Path, identity: str) -> str:
    relative, qualified = identity.split("::", 1)
    node = ast.parse(_raw(repo, relative).decode("utf-8"))
    for part in qualified.split("."):
        node = next(n for n in node.body if isinstance(n,
            (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == part)
    return hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()


def build_error_hardening_binding(repo: Path, cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Rebuild the new Master's gates from physical, current, committed proof bytes."""
    try:
        return _build_error_hardening(repo, cases)
    except (OSError, KeyError, TypeError, ValueError, StopIteration, AttributeError):
        raise PingSuccessorBindingError("ERROR_HARDENING_PROOF_MISSING_INVALID_OR_STALE") from None


def _build_error_hardening(repo: Path, cases: list[dict[str, Any]]) -> dict[str, Any]:
    documents, binding = {}, {}
    for field, filename in ERROR_PROOF_FILES.items():
        relative = f"{ERROR_HARDENING_EVIDENCE_ROOT}/{filename}"
        raw = _raw(repo, relative)
        document = json.loads(raw)
        # The admission manifest is a closed legacy source-lineage value object;
        # its enclosing new proof references bind it to this Master.
        if field != "historical_admission_manifest":
            _require(document.get("status") == "PASS"
                and document.get("master_authorization_sha256") == ERROR_HARDENING_SOURCE_SHA256,
                "ERROR_PROOF_MASTER_OR_STATUS_DRIFT")
        documents[field] = document
        binding[field] = {"identity": relative, "sha256": hashlib.sha256(raw).hexdigest()}

    official = documents["authoritative_error_semantics"]
    _require(official.get("SSE_ERROR_IS_PROVIDER_ERROR") is True
        and official.get("OFFICIAL_ERROR_EVENT_TERMINATES_ITERATION") is True
        and bool(official.get("AUTHORITATIVE_SOURCE_REFERENCES")), "ERROR_SEMANTICS_UNRESOLVED")
    ping = documents["authoritative_ping_semantics"]
    _require(ping.get("SEMANTIC_MESSAGE_TERMINAL_EVENT") == "message_stop"
        and ping.get("POST_MESSAGE_STOP_PING_COMPATIBILITY_INFERENCE") == "SUPPORTED"
        and bool(ping.get("AUTHORITATIVE_SOURCE_REFERENCES")), "PING_SEMANTICS_UNRESOLVED")
    precedence = documents["error_precedence_contract"]
    _require(precedence.get("PRIMARY_TERMINAL_CAUSE") == "PROVIDER_ERROR"
        and precedence.get("SECONDARY_POST_ERROR_PING_COUNT") == 1
        and precedence.get("SECONDARY_POST_ERROR_TIMEOUT_PRESENT") is True,
        "ERROR_CAUSAL_CONTRACT_NOT_PASS")
    normalization = documents["nonobject_error_normalization"]
    _require(set(normalization.get("payload_shapes", [])) == {
        "object", "string", "number", "boolean", "array", "null", "raw", "empty"}
        and type(normalization.get("ATTRIBUTEERROR_FROM_SSE_ERROR_PAYLOAD_COUNT")) is int
        and normalization["ATTRIBUTEERROR_FROM_SSE_ERROR_PAYLOAD_COUNT"] == 0,
        "ERROR_NORMALIZATION_CONTRACT_NOT_PASS")
    for doc in (precedence, normalization):
        _current_sources(repo, doc["source_hashes"], required={"src/novel_flywheel/providers/anthropic.py"})

    request = documents["request_zero_diff"]
    zero_fields = ("OUTBOUND_REQUEST_BODY_CHANGED_COUNT", "MODEL_VISIBLE_REQUEST_BYTES_CHANGED_COUNT",
        "ROUTE_BINDING_CHANGED_COUNT", "OUTPUT_CAP_CHANGED_COUNT", "REASONING_POLICY_CHANGED_COUNT",
        "REQUEST_BUILDER_SOURCE_DIFF")
    _require(all(type(request.get(k)) is int and request[k] == 0 for k in zero_fields),
        "ERROR_REQUEST_ZERO_DIFF_NOT_PASS")
    inventory = request["inventory"]
    raw_inventory = (json.dumps(inventory, ensure_ascii=False, indent=2) + "\n").encode()
    _require(hashlib.sha256(raw_inventory).hexdigest() == request["before_inventory_sha256"]
        == request["after_inventory_sha256"] and type(request["request_count"]) is int
        and request["request_count"] >= 120 and len(inventory["request_rows"]) == request["request_count"],
        "ERROR_REQUEST_INVENTORY_DRIFT")
    _current_sources(repo, request["source_hashes"], required={
        "src/novel_flywheel/provider_payloads.py", "src/novel_flywheel/providers/http.py",
        "src/novel_flywheel/providers/registry.py", "src/novel_flywheel/context_policy.py"})
    ast_hashes = request["request_builder_ast_hashes"]
    _require(isinstance(ast_hashes, dict) and bool(ast_hashes), "ERROR_REQUEST_AST_SET_EMPTY")
    _require({"src/novel_flywheel/provider_payloads.py", "src/novel_flywheel/providers/http.py"}
        .issubset({identity.split("::", 1)[0] for identity in ast_hashes}), "ERROR_REQUEST_AST_SET_INCOMPLETE")
    for identity, hashes in ast_hashes.items():
        _require(hashes["before"] == hashes["after"] == _function_ast(repo, identity),
            "ERROR_REQUEST_AST_DRIFT")
    tree = ast.parse(_raw(repo, "src/novel_flywheel/providers/anthropic.py").decode("utf-8"))
    complete = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "complete")
    prefix = ast.dump(ast.Module(body=complete.body[:5], type_ignores=[]), include_attributes=False)
    _require(hashlib.sha256(prefix.encode()).hexdigest() == inventory["complete_request_prefix_ast_sha256"],
        "ERROR_REQUEST_PREFIX_DRIFT")

    matrix = documents["response_regression_matrix"]
    _require({c["id"] for c in matrix["cases"]} == set(range(1, 28))
        and len(matrix["cases"]) == 27 and all(c.get("status") == "PASS" for c in matrix["cases"])
        and all(type(matrix.get(k)) is int and matrix[k] == 0 for k in (
            "ATTRIBUTEERROR_FROM_SSE_ERROR_PAYLOAD_COUNT", "PROVIDER_ERROR_LOST_TO_LATER_TIMEOUT_COUNT",
            "POST_TERMINAL_ERROR_IGNORED_COUNT", "SHARED_PROTOCOL_REGRESSION_COUNT")),
        "ERROR_RESPONSE_MATRIX_NOT_PASS")
    _current_sources(repo, matrix["source_hashes"], required={
        "src/novel_flywheel/providers/anthropic.py", "src/novel_flywheel/providers/http.py",
        "src/novel_flywheel/provider_response_capture.py"})

    manifest, terminal = _validate_historical_sources(repo, cases, documents["historical_admission_manifest"])
    history_root = repo.resolve().parent / manifest.source_root_identity
    auth = documents["historical_source_authentication"]
    required_files = {reference.identity: reference.sha256 for proof in manifest.historical_cases
        for reference in proof.source_files.values()}
    required_files["final-manifest-v1.json"] = manifest.source_manifest_sha256
    _require(isinstance(auth["source_files"], dict)
        and all(auth["source_files"].get(path) == sha for path, sha in required_files.items())
        and auth.get("metadata_authentication_verified") is True
        and auth.get("journal_authentication_verified") is True,
        "ERROR_HISTORICAL_AUTHENTICATION_NOT_BOUND")
    for path, digest in auth["source_files"].items():
        _raw(history_root, path, digest)
    old = json.loads(_raw(history_root, "campaign/campaign-authorization-v1.json"))
    _require(auth["source_authorization_sha256"] == manifest.historical_cases[0].source_authorization_sha256
        and auth["source_execution_head"] == manifest.historical_cases[0].source_execution_head
        and auth["source_manifest_sha256"] == manifest.source_manifest_sha256
        and auth["verification_key_sha256"] == old["external_workload_evidence"]["verification_key"]["key_sha256"],
        "ERROR_HISTORICAL_AUTHENTICATION_IDENTITY_DRIFT")
    for index, proof in enumerate(manifest.historical_cases, 1):
        replay = documents[f"probe{index:02d}_exact_replay"]
        _require(replay["case_id"] == proof.case_id
            and replay["raw_capture_sha256"] == proof.source_capture_sha256
            and replay["canonical_input_tokens"] == proof.canonical_input_tokens
            and replay["canonical_output_tokens"] == proof.canonical_output_tokens
            and replay["http_status"] == 200 and replay["transport_complete"] is True,
            "ERROR_DISTINCT_REPLAY_DRIFT")
        _current_sources(repo, replay["source_hashes"], required={
            "src/novel_flywheel/providers/anthropic.py", "src/novel_flywheel/provider_response_capture.py"})
        if index == 2:
            _require(replay.get("POST_TERMINAL_PING_COUNT") == 3
                and replay.get("POST_TERMINAL_PING_IGNORED_COUNT") == 3, "ERROR_PING_REPLAY_REGRESSED")

    reviewers, reviewer_ids, reviewed_sources = [], set(), set()
    for index in range(1, 4):
        relative = f"{ERROR_HARDENING_EVIDENCE_ROOT}/independent-reviewer-{index}-v1.json"
        raw = _raw(repo, relative)
        reviewer = json.loads(raw)
        _require(reviewer.get("master_authorization_sha256") == ERROR_HARDENING_SOURCE_SHA256
            and reviewer.get("status") == "PASS" and reviewer.get("architecture") == "ARCHITECTURE_PASS"
            and reviewer.get("error_precedence_finding") == "CLOSED"
            and reviewer.get("nonobject_error_finding") == "CLOSED"
            and isinstance(reviewer.get("reviewer_id"), str) and bool(reviewer["reviewer_id"]),
            "ERROR_INDEPENDENT_REVIEW_NOT_PASS")
        reviewer_ids.add(reviewer["reviewer_id"])
        _current_sources(repo, reviewer["reviewed_source_hashes"])
        reviewed_sources.update(reviewer["reviewed_source_hashes"])
        reviewers.append({"identity": relative, "sha256": hashlib.sha256(raw).hexdigest()})
    _require(len(reviewer_ids) == 3 and ERROR_REVIEW_SOURCE_PATHS.issubset(reviewed_sources),
        "ERROR_REVIEW_COVERAGE_INCOMPLETE")
    binding.update(reviewer_receipts=reviewers, selected_probe_ordinals=list(range(3, 9)),
        historical_cases=[p.model_dump(mode="json") for p in manifest.historical_cases],
        excluded_prior_nonce_sha256s=[r["nonce_sha256"] for r in terminal["records"][:2]])
    return ErrorHardeningRecoveryProofs.model_validate(binding).model_dump(mode="json")
