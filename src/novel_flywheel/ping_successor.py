"""Closed, offline contracts for historical capacity admission and fresh selection.

The eight capacity obligations are immutable.  Admission of a historical
request never makes it a fresh dispatch, resets its nonce, or debits fresh usage.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator

PING_RECOVERY_SCHEMA = "FullShortPostMessageStopPingRecoveryAndSuccessorExecutionAuthorizationV1"
PING_RECOVERY_SOURCE_IDENTITY = "PROBE02_POST_MESSAGE_STOP_PING_ROOT_CAUSE_FIX_REPLAY_AND_END_TO_END_CONTINUE_MASTER"
PING_RECOVERY_SOURCE_SHA256 = "1a15d628ea81e3938cc4dbe99574f02b50c7a9d6f7eb59a1734e5d9328bc1cc2"
PING_EVIDENCE_ROOT = "docs/superpowers/reports/probe02-post-message-stop-ping-fix-successor-v1"
HISTORICAL_ADMISSION_SCHEMA = "HistoricalWorkloadEvidenceAdmissionV1"
ERROR_HARDENING_SCHEMA = "FullShortAnthropicErrorHardeningAndSuccessorExecutionAuthorizationV1"
ERROR_HARDENING_SOURCE_IDENTITY = "PROBE02_SHARED_ANTHROPIC_COMPATIBLE_ERROR_EVENT_HARDENING_MASTER"
ERROR_HARDENING_SOURCE_SHA256 = "d4314e0695ec95f80662015f0a6591a735405d881cd486e8770f4a584b8d0674"
ERROR_HARDENING_EVIDENCE_ROOT = "docs/superpowers/reports/probe02-anthropic-error-hardening-successor-v1"
SUCCESSOR_SCHEMAS = frozenset({PING_RECOVERY_SCHEMA, ERROR_HARDENING_SCHEMA})
LEGACY_CAMPAIGN_SCHEMAS = frozenset({
    "FullShortOneRoundBudgetUnblockedExecutionAuthorizationV1",
    "FullShortSharedProtocolSafeUsageRecoveryAndSuccessorExecutionAuthorizationV1",
})


def compact_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ProofReference(Closed):
    identity: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def relative(self):
        if (not self.identity or self.identity.strip() != self.identity
            or ":" in self.identity or "\\" in self.identity
            or any(p in {"", ".", ".."} for p in self.identity.split("/"))
            or any(ord(c) < 32 for c in self.identity)):
            raise ValueError("noncanonical proof path")
        return self


class HistoricalAdmissionProof(Closed):
    case_id: str
    disposition: Literal["HISTORICAL_PASS", "REPLAY_PROVEN_PASS"]
    source_authorization_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_execution_head: str = Field(pattern=r"^[0-9a-f]{40}$")
    source_nonce_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_capture_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_capture_metadata_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    canonical_input_tokens: int = Field(gt=0)
    canonical_output_tokens: int = Field(gt=0)
    acceptance_proven: Literal[True]
    replay_proof_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    source_files: dict[str, ProofReference]
    source_metadata_authentication_verified: Literal[True]
    source_journal_authentication_verified: Literal[True]
    current_request_identity_proven: Literal[True]

    @model_validator(mode="after")
    def source_identity(self):
        if not self.source_files:
            raise ValueError("missing historical source files")
        if self.case_id == "full-short-probe-01-draft_plain":
            if (self.canonical_input_tokens,
                self.canonical_output_tokens) != (89255, 25):
                raise ValueError("historical probe01 is not latest accepted request")
        elif self.case_id == "full-short-probe-02-polish_plain":
            if self.disposition != "REPLAY_PROVEN_PASS" or not self.replay_proof_sha256:
                raise ValueError("historical probe02 requires exact replay")
        else:
            raise ValueError("case is not eligible for historical admission")
        if self.disposition == "REPLAY_PROVEN_PASS" and not self.replay_proof_sha256:
            raise ValueError("replay-proven admission requires its own replay proof")
        return self


class HistoricalAdmissionManifest(Closed):
    schema_name: Literal["HistoricalWorkloadAdmissionManifestV1"] = Field(alias="schema")
    source_root_identity: Literal["full-short-shared-usage-successor-20260905-v1"]
    source_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    historical_cases: list[HistoricalAdmissionProof] = Field(min_length=1, max_length=2)
    old_authorization_reused_for_dispatch: Literal[False]
    old_nonce_reset_or_reused: Literal[False]
    fresh_dispatches: Literal[0]
    new_provider_credential_lookups: Literal[0]
    verification_key_read_for_authentication_only: Literal[True]


class PingRecoveryProofs(Closed):
    authoritative_ping_semantics: ProofReference
    exact_replay: ProofReference
    workload_disposition: ProofReference
    request_zero_diff: ProofReference
    response_regression_matrix: ProofReference
    historical_admission_manifest: ProofReference
    raw_capture_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    probe02_disposition: Literal["REPLAY_PROVEN_PASS", "FRESH_REPLACEMENT_REQUIRED"]
    selected_probe_ordinals: list[int]
    historical_cases: list[HistoricalAdmissionProof]
    excluded_prior_nonce_sha256s: list[str]

    @model_validator(mode="after")
    def partition(self):
        start = 3 if self.probe02_disposition == "REPLAY_PROVEN_PASS" else 2
        if self.selected_probe_ordinals != list(range(start, 9)):
            raise ValueError("successor dispatch selection drift")
        expected = ["full-short-probe-01-draft_plain"]
        if start == 3:
            expected.append("full-short-probe-02-polish_plain")
        if [p.case_id for p in self.historical_cases] != expected:
            raise ValueError("historical/fresh partition drift")
        if len({p.source_nonce_sha256 for p in self.historical_cases}) != len(expected):
            raise ValueError("historical nonce reused")
        if (len(self.excluded_prior_nonce_sha256s) != 2
            or len(set(self.excluded_prior_nonce_sha256s)) != 2
            or any(len(n) != 64 or any(c not in "0123456789abcdef" for c in n)
                for n in self.excluded_prior_nonce_sha256s)
            or not {p.source_nonce_sha256 for p in self.historical_cases}.issubset(self.excluded_prior_nonce_sha256s)):
            raise ValueError("prior nonce exclusion drift")
        for p in self.historical_cases:
            if p.case_id == "full-short-probe-01-draft_plain" and p.disposition != "HISTORICAL_PASS":
                raise ValueError("legacy ping probe01 disposition drift")
            if p.disposition == "REPLAY_PROVEN_PASS" and (
                p.replay_proof_sha256 != self.exact_replay.sha256
                or p.source_capture_sha256 != self.raw_capture_sha256):
                raise ValueError("replay provenance drift")
        return self


class ErrorHardeningRecoveryProofs(Closed):
    """Fresh error-hardening authority; both prior calls require distinct replays."""
    authoritative_error_semantics: ProofReference
    authoritative_ping_semantics: ProofReference
    error_precedence_contract: ProofReference
    nonobject_error_normalization: ProofReference
    probe01_exact_replay: ProofReference
    probe02_exact_replay: ProofReference
    request_zero_diff: ProofReference
    response_regression_matrix: ProofReference
    historical_admission_manifest: ProofReference
    historical_source_authentication: ProofReference
    reviewer_receipts: list[ProofReference] = Field(min_length=3, max_length=3)
    selected_probe_ordinals: list[int]
    historical_cases: list[HistoricalAdmissionProof] = Field(min_length=2, max_length=2)
    excluded_prior_nonce_sha256s: list[str]

    @model_validator(mode="after")
    def partition(self):
        if self.selected_probe_ordinals != list(range(3, 9)):
            raise ValueError("error-hardening successor selection drift")
        if [p.case_id for p in self.historical_cases] != [
            "full-short-probe-01-draft_plain", "full-short-probe-02-polish_plain"
        ]:
            raise ValueError("historical/fresh partition drift")
        if self.probe01_exact_replay.identity == self.probe02_exact_replay.identity:
            raise ValueError("distinct replay sources required")
        for proof, replay, usage in zip(self.historical_cases,
            (self.probe01_exact_replay, self.probe02_exact_replay),
            ((89255, 25), (137304, 64)), strict=True):
            if (proof.disposition != "REPLAY_PROVEN_PASS"
                or proof.replay_proof_sha256 != replay.sha256
                or (proof.canonical_input_tokens, proof.canonical_output_tokens) != usage):
                raise ValueError("distinct replay provenance drift")
        nonces = [p.source_nonce_sha256 for p in self.historical_cases]
        if len(set(nonces)) != 2 or self.excluded_prior_nonce_sha256s != nonces:
            raise ValueError("prior nonce exclusion drift")
        if len({r.identity for r in self.reviewer_receipts}) != 3:
            raise ValueError("three distinct reviewer receipts required")
        return self


def is_selected_successor(authorization: Mapping[str, Any]) -> bool:
    schema = authorization.get("schema")
    if schema not in SUCCESSOR_SCHEMAS | LEGACY_CAMPAIGN_SCHEMAS:
        raise ValueError("unknown campaign authorization schema")
    return schema in SUCCESSOR_SCHEMAS


def selected_ordinals(authorization: Mapping[str, Any]) -> tuple[int, ...]:
    if not is_selected_successor(authorization):
        return tuple(range(1, 9))
    return tuple(authorization["post_message_stop_ping_recovery"]["selected_probe_ordinals"])


def historical_by_case(authorization: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    if not is_selected_successor(authorization):
        return {}
    return {p["case_id"]: p for p in authorization["post_message_stop_ping_recovery"]["historical_cases"]}


def capacity_authorized_cases(authorization: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    history = historical_by_case(authorization)
    return tuple({**case, **({"historical_admission_sha256": compact_sha(history[case["case_id"]])}
        if case["case_id"] in history else {})} for case in authorization["probe_campaign"]["cases"])


def selected_budget(authorization: Mapping[str, Any]) -> dict[str, int]:
    selected = selected_ordinals(authorization)
    probe_input = sum(c["estimated_input_tokens"] for c in authorization["probe_campaign"]["cases"]
        if c["ordinal"] in selected)
    total = 2_373_076 + probe_input
    return {"exact_probe_fixture_input_tokens": probe_input,
        "exact_pre_dispatch_estimated_input_tokens": total,
        "plan_derived_max_input_tokens": (total * 120 + 99) // 100,
        "plan_derived_max_provider_requests": 96 + len(selected)}


def expected_evidence(authorization: Mapping[str, Any], authorization_sha: str,
    case: Mapping[str, Any], key_id: str):
    from novel_flywheel.external_workload_evidence import ExpectedWorkloadEvidenceV1
    route = case["route"]
    history = historical_by_case(authorization)
    return ExpectedWorkloadEvidenceV1(authorization_sha256=authorization_sha,
        final_execution_head=authorization["frozen_execution"]["final_execution_head"],
        provider=route["provider"], operator=route["operator"], destination=route["destination"],
        protocol=route["protocol"], model=route["model"], route_fingerprint_sha256=route["route_fingerprint"],
        case_id=case["case_id"], fixture_sha256=case["fixture_sha256"],
        request_family_sha256=case["request_family_sha256"], request_sha256=case["request_sha256"],
        input_tokens=case["estimated_input_tokens"], requested_output_tokens=case["wire_requested_output_cap"],
        key_id=key_id, historical_admission_sha256=(compact_sha(history[case["case_id"]])
            if case["case_id"] in history else None))
