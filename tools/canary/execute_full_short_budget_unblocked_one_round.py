"""One-round controller for the budget-unblocked Full Short campaign.

This module is inert until its explicit phase functions are called.  It keeps
the campaign authorization, append-only state, probe captures, signed workload
evidence, gate receipts, and nested Full Short authorization outside Git.  A
state reserved for probes or Full Short is never automatically resumed: an
uncertain process exit therefore consumes the phase instead of redispatching.
"""

from __future__ import annotations

from novel_flywheel.ping_successor import (
    PING_RECOVERY_SCHEMA, PING_RECOVERY_SOURCE_IDENTITY, PING_RECOVERY_SOURCE_SHA256,
    selected_ordinals, selected_budget, historical_by_case, capacity_authorized_cases,
    expected_evidence, SUCCESSOR_SCHEMAS, ERROR_HARDENING_SCHEMA,
    ERROR_HARDENING_SOURCE_IDENTITY, ERROR_HARDENING_SOURCE_SHA256,
)
from novel_flywheel.full_short_probe_campaign import SelectedSuccessorProbePlan
from novel_flywheel.external_workload_evidence import seal_historical_workload_admission_v1
from tools.canary.ping_successor_binding import (
    build_ping_recovery_binding, build_error_hardening_binding, PingSuccessorBindingError,
)

import argparse
import ast
import asyncio
import hashlib
import hmac
import json
import math
import os
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
import subprocess
import time
from typing import Any
from xml.etree import ElementTree

from novel_flywheel.db import Database
from novel_flywheel.causal_chain import analyze_short_causal_chain
from novel_flywheel.execution_manifest import (
    execution_manifest_sha256,
    execution_manifest_issues,
    parse_execution_manifest,
)
from novel_flywheel.draft_split import (
    validate_semantic_receipt,
    validate_whole_draft_receipt,
)
from novel_flywheel.external_workload_evidence import (
    ExpectedWorkloadEvidenceV1,
    ExternalWorkloadEvidenceError,
    VerifiedWorkloadEvidenceV1,
    validate_external_workload_evidence_v1,
)
from novel_flywheel.full_short_campaign_authorization import (
    AUTHORIZATION_SOURCE_IDENTITY,
    AUTHORIZATION_SOURCE_SHA256,
    SHARED_USAGE_RECOVERY_SCHEMA,
    SHARED_USAGE_RECOVERY_SOURCE_IDENTITY,
    SHARED_USAGE_RECOVERY_SOURCE_SHA256,
    EXACT_READY_PROJECT_ID,
    EXACT_READY_PROJECT_ID_SHA256,
    FullShortCampaignAuthorizationError,
    canonical_json_bytes,
    render_full_short_one_round_budget_unblocked_execution_authorization_v1,
    validate_external_evidence_against_outer_v1,
    validate_full_short_one_round_budget_unblocked_execution_authorization_v1,
    validate_post_probe_full_short_authorization_derivation_v1,
)
from novel_flywheel.full_short_execution import (
    FullShortDurableExecutionStoreV1,
    FullShortExecutionPolicyV1,
    LOGICAL_STAGE_RECOVERY_POLICY_V1,
    build_full_short_outer_campaign_usage_guard_v1,
    build_full_short_completion_receipt_v1,
    render_full_short_canonical_authorization_v1,
    validate_full_short_canonical_authorization_v1,
)
from novel_flywheel.full_short_runtime_kernel import (
    DurableExecutionJournalV1,
    ExecutionState,
)
from novel_flywheel.maintenance_authority import validate_maintenance_reduction
from novel_flywheel.planning_semantics import (
    PlanningSemanticDraftV2,
    compile_planning_semantic_v2,
)
from novel_flywheel.providers.registry import ProviderRegistry
from novel_flywheel.providers.http import SingleDispatchTransportPolicyV1
from novel_flywheel.project_transactions import (
    ProjectMutationJournalV1,
    canonical_json_sha256,
)
from novel_flywheel.projects import Project
from novel_flywheel.quality import issue_ledger, review_windows
from novel_flywheel.quality_summary import effective_han_characters
from novel_flywheel.receipt_contracts import (
    validate_final_review_verdict_receipt,
)
from novel_flywheel.runtime_fingerprint_build import domain_sha256
from novel_flywheel.secrets import KeyringSecretStore, MemorySecretStore
from novel_flywheel.short_canonical_promotion import (
    MaintenanceProposalInventoryV1,
    ShortCanonicalCommitReceiptV1,
    candidate_from_window_envelope,
    proposal_units_from_candidate,
)
from novel_flywheel.workflows import (
    WorkflowService,
    validate_short_maintenance_business_complete_v2,
)
from tools.canary.first_trustworthy_full_short_runner import (
    collect_live_bindings,
    execute_full_short_control_plane,
)
from tools.canary.full_short_budget_unblocked_campaign import (
    EXACT_PROBE_INPUT_TOKENS,
    GuardedRealCampaignResult,
    SyntheticProbeFixture,
    _run_guarded_campaign_with_registry_v1,
    build_synthetic_probe_fixtures,
)


EXPECTED_BRANCH = "r1-ptr3/planning-repair-finding-propagation-20260817"
OUTER_MAX_INPUT_TOKENS = 4_000_000
MAX_PROVIDER_REQUESTS = 144
MAX_HTTP_POST_ATTEMPTS = 144
MAX_NETWORK_REQUESTS = 144
MAX_GENERATED_OUTPUT_TOKENS = 2_000_000
MAX_OUTPUT_TOKENS_PER_REQUEST = 32_000
MAX_ELAPSED_SECONDS = 36_000
DRY_EXECUTION_ID = "private-current-project-dry-run"

_BUDGET_RECALCULATION_PATH = Path(
    "docs/superpowers/reports/"
    "full-short-end-to-end-one-round-budget-unblocked-preparation-v1/"
    "campaign-input-budget-recalculation-v2.json"
)
_PROBE_DERIVATION_PATH = Path(
    "docs/superpowers/reports/"
    "full-short-end-to-end-one-round-budget-unblocked-preparation-v1/"
    "probe-family-derivation-v1.json"
)
_ATTEMPT_MATRIX_PATH = Path(
    "docs/superpowers/reports/"
    "full-short-capacity-final-one-round-confirmation-v1/"
    "exact-ready-authoritative-physical-attempt-matrix-v1.json"
)
_PINNED_BUDGET_SOURCE_SHA256S = {
    _BUDGET_RECALCULATION_PATH: "be2fd1c00986c8a37b36461473a112c25a91c7e5cc5e756092eb249851ddbbb5",
    _PROBE_DERIVATION_PATH: "38b641d35b1466d59dd9efd033bb330de2de369a77fbde84fad06eec2acd3eae",
    _ATTEMPT_MATRIX_PATH: "b8a49e188b0b13187e8730cbbbd48714fdb71a6aa5a16bd4f3ee25edf61e0287",
}


def _load_pinned_plan_input_cap() -> int:
    """Fail module loading closed if its committed budget source was replaced."""

    path = Path(__file__).resolve().parents[2] / _BUDGET_RECALCULATION_PATH
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != _PINNED_BUDGET_SOURCE_SHA256S[
        _BUDGET_RECALCULATION_PATH
    ]:
        raise RuntimeError("BUDGET_DERIVATION_SOURCE_DRIFT")
    value = json.loads(raw.decode("utf-8"))
    cap = value.get("PLAN_DERIVED_MAX_INPUT_TOKENS")
    if type(cap) is not int or cap <= 0:
        raise RuntimeError("BUDGET_DERIVATION_SOURCE_INVALID")
    return cap


PLAN_DERIVED_MAX_INPUT_TOKENS = _load_pinned_plan_input_cap()


class OneRoundCampaignError(RuntimeError):
    """Fixed, non-secret campaign failure."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True)
class MaterializedCampaignV1:
    authorization: dict[str, Any]
    authorization_raw: bytes
    authorization_sha256: str
    evidence_root: Path
    preprobe_full_short_policy: dict[str, Any]
    preprobe_full_short_public_bindings: dict[str, Any]


@dataclass(frozen=True)
class PostProbeAuthorizationV1:
    policy: dict[str, Any]
    public_bindings: dict[str, Any]
    authorization_raw: bytes
    authorization_sha256: str


@dataclass(frozen=True)
class MandatoryGateReceiptsV1:
    dry_run_receipt: bytes
    size_matrix_receipt: bytes
    strict_l3_receipt: bytes
    reviewer_receipts: tuple[bytes, ...]

    @staticmethod
    def _canonical(raw: bytes) -> dict[str, Any]:
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeError, ValueError, TypeError):
            raise OneRoundCampaignError("MANDATORY_GATE_RECEIPT_INVALID") from None
        if not isinstance(value, dict) or canonical_json_bytes(value) != raw:
            raise OneRoundCampaignError("MANDATORY_GATE_RECEIPT_INVALID")
        return value

    @staticmethod
    def _required_binding_fields() -> set[str]:
        return {
            "outer_authorization_sha256",
            "nested_authorization_sha256",
            "probe_evidence_manifest_sha256",
            "previous_journal_state_sha256",
            "generated_at_unix_seconds",
        }

    @classmethod
    def _with_evidence_binding(
        cls, raw: bytes,
    ) -> tuple[dict[str, Any], str, str]:
        body = cls._canonical(raw)
        path = body.pop("evidence_path", None)
        digest = body.get("evidence_sha256")
        if (
            not isinstance(path, str) or not Path(path).is_absolute()
            or not _is_sha256(digest)
        ):
            raise OneRoundCampaignError("MANDATORY_GATE_RECEIPT_INVALID")
        return body, path, str(digest)

    def validate(self, *, final_head: str, core_tree_sha256: str) -> None:
        dry, _dry_path, _dry_sha = self._with_evidence_binding(
            self.dry_run_receipt
        )
        size, _size_path, _size_sha = self._with_evidence_binding(
            self.size_matrix_receipt
        )
        strict, _strict_path, _strict_sha = self._with_evidence_binding(
            self.strict_l3_receipt
        )
        common = self._required_binding_fields()
        if set(dry) != {
            "schema", "source_schema", "final_execution_head", "project_id",
            "status", "evidence_sha256", *common,
        } or any(not _is_sha256(dry[field]) for field in common - {
            "generated_at_unix_seconds",
        }) or type(dry["generated_at_unix_seconds"]) is not int or {
            key: dry[key] for key in (
                "schema", "source_schema", "final_execution_head",
                "project_id", "status", "evidence_sha256",
            )
        } != {
            "schema": "FullShortExactReadyDryRunGateReceiptV1",
            "source_schema": "FirstTrustworthyFullShortPrivateDryRunV2",
            "final_execution_head": final_head,
            "project_id": EXACT_READY_PROJECT_ID,
            "status": "PASS_EXACT_READY_TARGET",
            "evidence_sha256": dry.get("evidence_sha256"),
        }:
            raise OneRoundCampaignError("MANDATORY_FULL_SHORT_GATE_FAILED")
        if set(size) != {
            "schema", "source_schema", "final_execution_head", "sizes",
            "segmentation_behavior", "physical_envelope_bounded",
            "evidence_sha256", *common,
        } or any(not _is_sha256(size[field]) for field in common - {
            "generated_at_unix_seconds",
        }) or type(size["generated_at_unix_seconds"]) is not int or {
            key: size[key] for key in (
                "schema", "source_schema", "final_execution_head", "sizes",
                "segmentation_behavior", "physical_envelope_bounded",
                "evidence_sha256",
            )
        } != {
            "schema": "FullShortSizeMatrixGateReceiptV1",
            "source_schema": "FullShortHttpSeamProductionLengthMatrixV1",
            "final_execution_head": final_head,
            "sizes": [13000, 20000, 30000],
            "segmentation_behavior": "PASS",
            "physical_envelope_bounded": "YES",
            "evidence_sha256": size.get("evidence_sha256"),
        }:
            raise OneRoundCampaignError("MANDATORY_FULL_SHORT_GATE_FAILED")
        if set(strict) != {
            "schema", "source_schema", "final_execution_head",
            "core_tree_sha256", "status", "warnings", "blockers",
            "new_capacity_regression_count",
            "new_runtime_kernel_regression_count",
            "new_authority_regression_count",
            "new_model_visible_literary_regression_count",
            "evidence_sha256", *common,
        } or any(not _is_sha256(strict[field]) for field in common - {
            "generated_at_unix_seconds",
        }) or type(strict["generated_at_unix_seconds"]) is not int or {
            key: strict[key] for key in (
                "schema", "source_schema", "final_execution_head",
                "core_tree_sha256", "status", "warnings", "blockers",
                "new_capacity_regression_count",
                "new_runtime_kernel_regression_count",
                "new_authority_regression_count",
                "new_model_visible_literary_regression_count",
                "evidence_sha256",
            )
        } != {
            "schema": "FullShortStrictL3GateReceiptV1",
            "source_schema": "NovelDevCouncilStrictInspectionV1",
            "final_execution_head": final_head,
            "core_tree_sha256": core_tree_sha256,
            "status": "PASS", "warnings": 0, "blockers": 0,
            "new_capacity_regression_count": 0,
            "new_runtime_kernel_regression_count": 0,
            "new_authority_regression_count": 0,
            "new_model_visible_literary_regression_count": 0,
            "evidence_sha256": strict.get("evidence_sha256"),
        }:
            raise OneRoundCampaignError("MANDATORY_FULL_SHORT_GATE_FAILED")
        roles = {
            "capacity_segmentation_runtime",
            "authority_storystate_canon",
            "recovery_exact_once_capture_restart",
            "route_evidence_budget_privacy",
            "literary_visible_invariance_baseline_skill",
        }
        if len(self.reviewer_receipts) != 5:
            raise OneRoundCampaignError("MANDATORY_FULL_SHORT_GATE_FAILED")
        observed = set()
        identities = set()
        for raw in self.reviewer_receipts:
            review, _review_path, _review_sha = self._with_evidence_binding(raw)
            if set(review) != {
                "schema", "final_execution_head", "core_tree_sha256",
                "source_schema", "reviewer_role", "reviewer_agent_identity",
                "status", "evidence_sha256", *common,
            } or (
                review["schema"] != "FullShortArchitectureReviewGateReceiptV1"
                or review["source_schema"]
                != "FullShortArchitectureReviewArtifactV1"
                or review["final_execution_head"] != final_head
                or review["core_tree_sha256"] != core_tree_sha256
                or review["status"] != "ARCHITECTURE_PASS"
                or review["reviewer_role"] not in roles
                or not isinstance(review["reviewer_agent_identity"], str)
                or not review["reviewer_agent_identity"].strip()
                or not _is_sha256(review["evidence_sha256"])
                or any(not _is_sha256(review[field]) for field in common - {
                    "generated_at_unix_seconds",
                })
                or type(review["generated_at_unix_seconds"]) is not int
            ):
                raise OneRoundCampaignError("MANDATORY_FULL_SHORT_GATE_FAILED")
            observed.add(review["reviewer_role"])
            identities.add(review["reviewer_agent_identity"])
        if observed != roles or len(identities) != 5:
            raise OneRoundCampaignError("MANDATORY_FULL_SHORT_GATE_FAILED")

    def evidence_bindings(self) -> tuple[tuple[str, str], ...]:
        raws = (
            self.dry_run_receipt, self.size_matrix_receipt,
            self.strict_l3_receipt, *self.reviewer_receipts,
        )
        return tuple(
            (path, digest)
            for _body, path, digest in (
                self._with_evidence_binding(raw) for raw in raws
            )
        )

    def document(self) -> dict[str, Any]:
        return {
            "dry_run_receipt_sha256": hashlib.sha256(
                self.dry_run_receipt
            ).hexdigest(),
            "size_matrix_receipt_sha256": hashlib.sha256(
                self.size_matrix_receipt
            ).hexdigest(),
            "strict_l3_receipt_sha256": hashlib.sha256(
                self.strict_l3_receipt
            ).hexdigest(),
            "reviewer_report_sha256s": [
                hashlib.sha256(raw).hexdigest()
                for raw in self.reviewer_receipts
            ],
        }


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _json_sha256(value: object) -> str:
    raw = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


_MANDATORY_REVIEW_ROLES = {
    "capacity_segmentation_runtime",
    "authority_storystate_canon",
    "recovery_exact_once_capture_restart",
    "route_evidence_budget_privacy",
    "literary_visible_invariance_baseline_skill",
}
_FULL_SHORT_REQUIRED_ARTIFACTS = {
    "planning-semantic-v2.json",
    "short-causal-chain.json",
    "short-execution-index.json",
    "draft.md",
    "polish.md",
    "final-review-evidence.json",
    "quality-report.json",
    "draft-integrity.json",
}
_FULL_SHORT_REQUIRED_GATE_ROLES = {
    "planning", "draft", "review", "polish", "final_review",
}
_GATE_CAMPAIGN_BINDING_FIELDS = {
    "outer_authorization_sha256", "nested_authorization_sha256",
    "probe_evidence_manifest_sha256", "previous_journal_state_sha256",
    "generated_at_unix_seconds",
}


def _require_gate_source_shape_v1(
    artifact: Mapping[str, Any], fields: set[str], reason: str,
) -> None:
    if set(artifact) != fields | _GATE_CAMPAIGN_BINDING_FIELDS:
        raise OneRoundCampaignError(reason)


def _external_file_bytes_v1(
    reference: object, *, repo: Path, reason: str,
) -> tuple[bytes, Path, str]:
    """Resolve and hash a concrete immutable raw-evidence file outside Git."""

    if not isinstance(reference, Mapping) or set(reference) != {"path", "sha256"}:
        raise OneRoundCampaignError(reason)
    path_value = reference.get("path")
    expected_sha256 = reference.get("sha256")
    if not isinstance(path_value, str) or not _is_sha256(expected_sha256):
        raise OneRoundCampaignError(reason)
    try:
        path = _require_outside_repo(repo, Path(path_value), reason)
        raw = path.read_bytes()
    except (OSError, ValueError, OneRoundCampaignError):
        raise OneRoundCampaignError(reason) from None
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    if not raw or actual_sha256 != expected_sha256:
        raise OneRoundCampaignError(reason)
    return raw, path, actual_sha256


def _external_json_v1(
    reference: object, *, repo: Path, reason: str, canonical: bool = False,
) -> tuple[dict[str, Any], Path, str]:
    raw, path, digest = _external_file_bytes_v1(
        reference, repo=repo, reason=reason,
    )
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError, TypeError):
        raise OneRoundCampaignError(reason) from None
    if not isinstance(value, dict) or (canonical and canonical_json_bytes(value) != raw):
        raise OneRoundCampaignError(reason)
    return value, path, digest


def _repository_file_sha256_v1(repo: Path, relative: object) -> str:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise OneRoundCampaignError("MANDATORY_GATE_REPOSITORY_PATH_INVALID")
    candidate = (repo / relative).resolve()
    try:
        candidate.relative_to(repo.resolve(strict=True))
    except ValueError:
        raise OneRoundCampaignError("MANDATORY_GATE_REPOSITORY_PATH_INVALID") from None
    if not candidate.is_file():
        raise OneRoundCampaignError("MANDATORY_GATE_REPOSITORY_PATH_INVALID")
    return hashlib.sha256(candidate.read_bytes()).hexdigest()


def _core_review_sha256_v1(repo: Path, core_paths: Sequence[str]) -> str:
    snapshot = [
        {
            "path": path,
            "fingerprint": {
                "exists": True,
                "kind": "file",
                "sha256": _repository_file_sha256_v1(repo, path),
            },
        }
        for path in sorted(set(core_paths))
    ]
    return _json_sha256(snapshot)


def _raw_evidence_document_v1(
    *, gate_ordinal: int, kind: str, path: Path, sha256: str,
) -> dict[str, Any]:
    return {
        "gate_ordinal": gate_ordinal,
        "kind": kind,
        "source_path": str(path),
        "evidence_sha256": sha256,
    }


def _load_canonical_gate_source(raw: bytes) -> dict[str, Any]:
    """Load a source artifact, never a prose assertion posing as evidence."""

    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError, TypeError):
        raise OneRoundCampaignError("MANDATORY_GATE_SOURCE_NOT_CANONICAL_JSON") from None
    if not isinstance(value, dict) or canonical_json_bytes(value) != raw:
        raise OneRoundCampaignError("MANDATORY_GATE_SOURCE_NOT_CANONICAL_JSON")
    return value


def _require_gate_campaign_binding(
    artifact: Mapping[str, Any], *, outer_sha256: str, nested_sha256: str,
    probe_manifest_sha256: str, previous_state_sha256: str,
    campaign_started_unix_seconds: int, now_unix_seconds: int,
) -> dict[str, Any]:
    expected = {
        "outer_authorization_sha256": outer_sha256,
        "nested_authorization_sha256": nested_sha256,
        "probe_evidence_manifest_sha256": probe_manifest_sha256,
        "previous_journal_state_sha256": previous_state_sha256,
    }
    if any(artifact.get(key) != value for key, value in expected.items()):
        raise OneRoundCampaignError("MANDATORY_GATE_CAMPAIGN_BINDING_INVALID")
    generated = artifact.get("generated_at_unix_seconds")
    if (
        type(generated) is not int
        or generated < campaign_started_unix_seconds
        or generated > now_unix_seconds + 1
    ):
        raise OneRoundCampaignError("MANDATORY_GATE_TIMESTAMP_INVALID")
    return {**expected, "generated_at_unix_seconds": generated}


def _validate_full_short_stage_artifacts_v1(
    *, artifacts: Mapping[str, bytes], base_story_state: Mapping[str, Any],
    project: Mapping[str, Any], final_manuscript: str, chapter_bytes: bytes,
    narrative_integrity: Mapping[str, Any],
) -> None:
    """Apply production artifact parsers to the exported seven-stage chain."""

    try:
        parsed = {
            name: json.loads(raw.decode("utf-8"))
            for name, raw in artifacts.items() if name.endswith(".json")
        }
        semantic = PlanningSemanticDraftV2.model_validate(
            parsed["planning-semantic-v2.json"]
        )
        state_data = base_story_state["data"]
        outline = state_data.get("outline")
        if not isinstance(outline, Mapping):
            raise ValueError("formal outline authority missing")
        formal_events = outline.get("events")
        formal_ending = state_data.get("ending")
        if (
            not isinstance(formal_events, list) or not formal_events
            or not all(isinstance(item, Mapping) for item in formal_events)
            or not isinstance(formal_ending, Mapping)
        ):
            raise ValueError("formal planning authority missing")
        compiled = compile_planning_semantic_v2(
            semantic, [dict(item) for item in formal_events],
            formal_ending=dict(formal_ending),
            expected_segment_count=len(semantic.segments),
        )
        expected_event_ids = [
            str(item.get("id") or item.get("event_id") or "").strip().upper()
            for item in formal_events
        ]
        if any(not item for item in expected_event_ids):
            raise ValueError("formal event identity missing")

        causal = parsed["short-causal-chain.json"]
        target_words = project.get("target_words")
        if type(target_words) is not int or target_words < 1:
            raise ValueError("project target is invalid")
        if analyze_short_causal_chain(causal, target_words)["status"] == "invalid":
            raise ValueError("causal chain is invalid")
        if [
            str(item).strip().upper()
            for item in causal.get("covered_event_ids", [])
        ] != expected_event_ids:
            raise ValueError("causal coverage is stale")

        execution = parse_execution_manifest(
            parsed["short-execution-index.json"]
        )
        execution_sha256 = execution_manifest_sha256(execution)
        causal_sha256 = _json_sha256(causal)
        authority_hashes = {
            "outline_sha256": hashlib.sha256(
                str(outline.get("content") or "").encode("utf-8")
            ).hexdigest(),
            "planning_sha256": hashlib.sha256(
                compiled.plan.encode("utf-8")
            ).hexdigest(),
            "causal_chain_sha256": causal_sha256,
        }
        if (
            execution.status != "ready"
            or execution_manifest_issues(
                execution, expected_event_ids=expected_event_ids,
                segment_count=len(semantic.segments),
                authority_hashes=authority_hashes,
            )
        ):
            raise ValueError("execution manifest authority is invalid")
        WorkflowService._validate_short_authority_graph(
            compiled.document, causal, execution,
        )

        draft = artifacts["draft.md"].decode("utf-8")
        polish = artifacts["polish.md"].decode("utf-8")
        draft_segments = WorkflowService._split_segments(draft)
        polish_segments = WorkflowService._split_segments(polish)
        target_words = project.get("target_words")
        if (
            len(draft_segments) != len(semantic.segments)
            or len(polish_segments) != len(semantic.segments)
            or "\n\n".join(polish_segments) != final_manuscript
            or chapter_bytes != final_manuscript.encode("utf-8")
            or type(target_words) is not int
            or target_words < 1
            or any(
                not target_words <= effective_han_characters(text)
                <= int(target_words * 1.2)
                for text in (draft, polish, final_manuscript)
            )
        ):
            raise ValueError("draft/polish/promotion authority is stale")

        project_value = Project(
            id=str(project.get("id") or ""),
            title=str(project.get("title") or ""),
            mode=str(project.get("mode") or ""),
            path=Path("."), metadata=dict(project),
        )
        expected_beat_ids = [
            beat_id for segment in execution.segments
            for beat_id in segment.beat_ids
        ]

        def validate_integrity(
            integrity: Mapping[str, Any], *, source_text: str,
            source_segments: list[str], label: str,
        ) -> None:
            receipts = integrity.get("semantic_segment_receipts")
            if (
                integrity.get("status") != "passed"
                or integrity.get("draft_sha256")
                != hashlib.sha256(source_text.encode("utf-8")).hexdigest()
                or integrity.get("execution_manifest_sha256")
                != execution_sha256
                or not isinstance(receipts, list)
                or len(receipts) != len(execution.segments)
                or len(source_segments) != len(execution.segments)
            ):
                raise ValueError(f"{label} integrity authority is stale")
            for index, (segment, prose, receipt) in enumerate(zip(
                execution.segments, source_segments, receipts, strict=True,
            ), 1):
                contract = WorkflowService._manifest_segment_contract(
                    project_value, execution, dict(integrity), segment,
                    prose, index,
                )
                validate_semantic_receipt(contract, prose, receipt)
            validate_whole_draft_receipt(
                str(integrity.get("authority_sha256")
                    or execution.authority_sha256),
                source_text, source_segments, expected_beat_ids,
                integrity.get("whole_semantic_receipt"),
            )

        draft_integrity = parsed["draft-integrity.json"]
        validate_integrity(
            draft_integrity, source_text=draft,
            source_segments=draft_segments, label="draft",
        )
        resolved_final = WorkflowService._integrity_publication_segments(
            Path("."), dict(narrative_integrity), final_manuscript,
        )
        if resolved_final is None:
            raise ValueError("final narrative integrity cannot be reconstructed")
        final_segments, integrity_source_text = resolved_final
        validate_integrity(
            narrative_integrity, source_text=integrity_source_text,
            source_segments=final_segments, label="final",
        )

        evidence = parsed["final-review-evidence.json"]
        report = parsed["quality-report.json"]
        windows = evidence.get("windows")
        audit = evidence.get("audit")
        expected_windows = review_windows(final_manuscript)
        if (
            not isinstance(windows, list)
            or not isinstance(audit, Mapping)
            or report.get("status") != "passed"
            or report.get("terminal_review_complete") is not True
            or report.get("terminal_reviewed_hash")
            != hashlib.sha256(final_manuscript.encode("utf-8")).hexdigest()
            or report.get("final_review_evidence") != dict(audit)
            or audit.get("coverage") != 1.0
            or audit.get("window_count") != len(expected_windows)
            or audit.get("reviewed_windows") != len(expected_windows)
            or len(windows) != len(expected_windows)
        ):
            raise ValueError("final review authority is invalid")
        for actual, expected in zip(windows, expected_windows, strict=True):
            if (
                not isinstance(actual, Mapping)
                or actual.get("window") != expected["index"]
                or actual.get("start") != expected["start"]
                or actual.get("end") != expected["end"]
                or actual.get("manuscript_sha256")
                != hashlib.sha256(final_manuscript.encode("utf-8")).hexdigest()
                or actual.get("window_sha256") != hashlib.sha256(
                    expected["text"].encode("utf-8")
                ).hexdigest()
                or not str(actual.get("summary") or "").strip()
                or not isinstance(actual.get("issues"), list)
            ):
                raise ValueError("final review window authority is invalid")
        terminal_review = report.get("terminal_review")
        if not isinstance(terminal_review, Mapping):
            raise ValueError("terminal review is missing")
        verdict = dict(terminal_review)
        for metadata_field in (
            "style_reference_fidelity", "scoring_profile_id",
            "judge_signature",
        ):
            verdict.pop(metadata_field, None)
        validate_final_review_verdict_receipt(verdict)
    except (
        KeyError, UnicodeError, json.JSONDecodeError, TypeError, ValueError,
    ) as exc:
        raise OneRoundCampaignError("MANDATORY_DRY_RUN_GATE_FAILED") from exc


def _validate_durable_dry_chain_v1(
    *, repo: Path, receipts: Mapping[str, Any], durable_binding: object,
    completion: Mapping[str, Any], terminal: Mapping[str, Any],
    source_head: str, expected_project_sha256: str,
    authorized_runtime_authority: Mapping[str, Any],
    authorized_project_workload: Mapping[str, Any],
) -> tuple[dict[str, Any], list[tuple[str, Path, str]]]:
    """Re-read the stable production store and rebuild terminal authority."""

    try:
        authorization, authorization_path, authorization_sha = _external_json_v1(
            receipts.get("canonical_authorization"), repo=repo,
            reason="MANDATORY_DRY_RUN_RAW_EVIDENCE_INVALID",
        )
        policy, policy_path, policy_sha = _external_json_v1(
            receipts.get("authorization_policy"), repo=repo,
            reason="MANDATORY_DRY_RUN_RAW_EVIDENCE_INVALID",
        )
        public, public_path, public_sha = _external_json_v1(
            receipts.get("authorization_public_bindings"), repo=repo,
            reason="MANDATORY_DRY_RUN_RAW_EVIDENCE_INVALID",
        )
        validated = validate_full_short_canonical_authorization_v1(
            authorization_path.read_bytes(), policy=policy,
            public_bindings=public,
        )
        validated_body = dict(validated)
        validated_body.pop("authorization_text_sha256", None)
        if (
            validated_body != authorization
            or authorization.get("policy") != policy
            or authorization.get("public_bindings") != public
            or policy.get("run_id") != DRY_EXECUTION_ID
            or public.get("run_id") != DRY_EXECUTION_ID
            or policy.get("execution_head") != source_head
            or policy.get("project_id_sha256") != expected_project_sha256
            or public.get("runtime_authority")
            != dict(authorized_runtime_authority)
            or public.get("project_workload")
            != dict(authorized_project_workload)
        ):
            raise ValueError("dry authorization binding drift")
        if (
            not isinstance(durable_binding, Mapping)
            or set(durable_binding) != {"root", "store_root_sha256"}
        ):
            raise ValueError("durable store binding missing")
        store_root = Path(str(durable_binding["root"])).resolve(strict=True)
        try:
            store_root.relative_to(repo.resolve(strict=True))
        except ValueError:
            pass
        else:
            raise ValueError("durable store is inside repository")
        store = FullShortDurableExecutionStoreV1(
            repo_root=repo, store_root=store_root,
        )
        if (
            store.store_root_sha256 != durable_binding["store_root_sha256"]
            or store.store_root_sha256 != policy.get("store_root_sha256")
        ):
            raise ValueError("durable store path drift")

        control = receipts.get("control_store")
        if not isinstance(control, Mapping) or set(control) != {
            "permission", "approval", "nonce", "ledger", "completion",
        }:
            raise ValueError("durable control chain incomplete")
        control_values: dict[str, dict[str, Any]] = {}
        control_documents: list[tuple[str, Path, str]] = []
        seal_contracts = {
            "permission": (
                "novel-flywheel-full-short-permission-v1", "permission_sha256",
            ),
            "approval": (
                "novel-flywheel-full-short-jit-approval-v1",
                "signed_approval_sha256",
            ),
            "nonce": (
                "novel-flywheel-full-short-nonce-record-v1", "nonce_record_sha256",
            ),
            "ledger": (
                "novel-flywheel-full-short-dispatch-ledger-v1", "ledger_sha256",
            ),
            "completion": (
                "novel-flywheel-full-short-completion-receipt-v1",
                "completion_receipt_sha256",
            ),
        }
        for kind, (domain, field) in seal_contracts.items():
            raw, path, digest = _external_file_bytes_v1(
                control[kind], repo=repo,
                reason="MANDATORY_DRY_RUN_RAW_EVIDENCE_INVALID",
            )
            if raw != store._path(DRY_EXECUTION_ID, kind).read_bytes():
                raise ValueError("exported durable bytes drift")
            value = json.loads(raw.decode("utf-8"))
            control_values[kind] = FullShortDurableExecutionStoreV1._verify_seal(
                value, domain=domain, field=field,
                reason="DURABLE_CONTROL_SEAL_INVALID",
            )
            control_documents.append((f"durable_{kind}", path, digest))
        if control_values["completion"] != dict(completion):
            raise ValueError("durable completion export drift")

        ledger = control_values["ledger"]
        capacity = store.verify_completion_capacity_receipts(
            execution_id=DRY_EXECUTION_ID, policy=policy, ledger=ledger,
        )
        captures = store.verify_completion_capture_receipts(
            execution_id=DRY_EXECUTION_ID, policy=policy, ledger=ledger,
        )
        rebuilt = build_full_short_completion_receipt_v1(
            execution_id=DRY_EXECUTION_ID, policy=policy,
            durable_store=store,
            permission_sha256=control_values["permission"]["permission_sha256"],
            signed_approval_sha256=control_values["approval"][
                "signed_approval_sha256"
            ],
            nonce_sha256=control_values["nonce"]["nonce_sha256"],
            ledger=ledger, final_bindings=completion["final_bindings"],
            terminal_verification=terminal,
            capacity_admission_receipts=capacity,
        )
        # The production builder deliberately timestamps a fresh attestation.
        # Rebind that sole non-deterministic field to the persisted receipt and
        # reseal it, so every durable input/body field is still rebuilt and the
        # resulting document must then match byte-for-byte in value space.
        rebuilt["created_at"] = completion["created_at"]
        rebuilt["completion_receipt_sha256"] = domain_sha256(
            "novel-flywheel-full-short-completion-receipt-v1",
            {
                key: value for key, value in rebuilt.items()
                if key != "completion_receipt_sha256"
            },
        )
        if rebuilt != dict(completion):
            raise ValueError("completion rebuild drift")

        durable_export_documents: list[tuple[str, Path, str]] = []

        def exported_hashes(kind: str, items: object) -> list[str]:
            if not isinstance(items, list):
                raise ValueError("durable evidence list invalid")
            digests: list[str] = []
            for index, item in enumerate(items, 1):
                _raw, path, digest = _external_file_bytes_v1(
                    item, repo=repo,
                    reason="MANDATORY_DRY_RUN_RAW_EVIDENCE_INVALID",
                )
                digests.append(digest)
                durable_export_documents.append((
                    f"durable_{kind}_{index:03d}", path, digest,
                ))
            return sorted(digests)

        capacity_paths = sorted(store.capacity_receipt_root.glob("*.json"))
        if exported_hashes(
            "capacity", receipts.get("capacity_admission_receipts"),
        ) != sorted(
            hashlib.sha256(path.read_bytes()).hexdigest()
            for path in capacity_paths
        ) or len(capacity) != len(capacity_paths):
            raise ValueError("capacity receipt export drift")
        anchor_paths = sorted(store.capture_anchor_root.glob("*.json"))
        if exported_hashes(
            "capture_anchor", receipts.get("capture_anchors"),
        ) != sorted(
            hashlib.sha256(path.read_bytes()).hexdigest() for path in anchor_paths
        ) or len(captures) != len(anchor_paths):
            raise ValueError("capture anchor export drift")
        capture_root = store_root / "provider-response-captures-v1"
        exported_captures = receipts.get("provider_response_captures")
        if not isinstance(exported_captures, list):
            raise ValueError("capture export missing")
        expected_capture_files = {
            path.relative_to(capture_root).as_posix(): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in capture_root.rglob("*") if path.is_file()
        }
        actual_capture_files: dict[str, str] = {}
        for item in exported_captures:
            if not isinstance(item, Mapping) or set(item) != {
                "relative_path", "evidence",
            }:
                raise ValueError("capture export invalid")
            _raw, capture_path, digest = _external_file_bytes_v1(
                item["evidence"], repo=repo,
                reason="MANDATORY_DRY_RUN_RAW_EVIDENCE_INVALID",
            )
            actual_capture_files[str(item["relative_path"])] = digest
            durable_export_documents.append((
                f"durable_provider_capture_{len(actual_capture_files):03d}",
                capture_path, digest,
            ))
        if actual_capture_files != expected_capture_files:
            raise ValueError("capture export drift")

        runtime_raw, runtime_path, runtime_sha = _external_file_bytes_v1(
            receipts.get("runtime_journal"), repo=repo,
            reason="MANDATORY_DRY_RUN_RAW_EVIDENCE_INVALID",
        )
        stable_runtime = store_root / f"{DRY_EXECUTION_ID}.runtime-journal-v1.json"
        if runtime_raw != stable_runtime.read_bytes():
            raise ValueError("runtime journal export drift")
        runtime = DurableExecutionJournalV1.open(runtime_path)
        if (
            runtime.execution_id != DRY_EXECUTION_ID
            or runtime.state is not ExecutionState.COMPLETED
        ):
            raise ValueError("runtime journal incomplete")
        replay, replay_path, replay_sha = _external_json_v1(
            receipts.get("replay_proof"), repo=repo,
            reason="MANDATORY_DRY_RUN_RAW_EVIDENCE_INVALID",
        )
        if (
            replay.get("all_captured_synthetic_responses_exactly_replayable")
            is not True
            or replay.get("replayed_full_workflow_matches_final_artifact")
            is not True
        ):
            raise ValueError("replay proof incomplete")
        documents = [
            ("canonical_authorization", authorization_path, authorization_sha),
            ("authorization_policy", policy_path, policy_sha),
            ("authorization_public_bindings", public_path, public_sha),
            ("runtime_journal", runtime_path, runtime_sha),
            ("replay_proof", replay_path, replay_sha),
            *control_documents,
            *durable_export_documents,
        ]
        return ledger, documents
    except OneRoundCampaignError:
        raise
    except Exception as exc:
        raise OneRoundCampaignError("MANDATORY_DRY_RUN_GATE_FAILED") from exc


def _validate_dry_run_gate_source(
    artifact: Mapping[str, Any], *, final_head: str, repo: Path,
    gate_ordinal: int, authorized_runtime_authority: Mapping[str, Any],
    authorized_project_workload: Mapping[str, Any],
    authorized_runtime_authority_sha256: str,
    authorized_workload_sha256: str,
) -> list[dict[str, Any]]:
    """Rebuild the dry gate from raw output and isolated receipt evidence."""

    _require_gate_source_shape_v1(artifact, {
        "schema", "dry_run_output", "isolated_evidence_manifest",
    }, "MANDATORY_DRY_RUN_GATE_FAILED")
    if artifact.get("schema") != "FullShortExactReadyDryRunGateSourceV2":
        raise OneRoundCampaignError("MANDATORY_DRY_RUN_GATE_FAILED")
    dry, dry_path, dry_sha = _external_json_v1(
        artifact.get("dry_run_output"), repo=repo,
        reason="MANDATORY_DRY_RUN_RAW_EVIDENCE_INVALID",
    )
    manifest, manifest_path, manifest_sha = _external_json_v1(
        artifact.get("isolated_evidence_manifest"), repo=repo,
        reason="MANDATORY_DRY_RUN_RAW_EVIDENCE_INVALID",
    )
    expected_project_sha = hashlib.sha256(
        EXACT_READY_PROJECT_ID.encode("utf-8")
    ).hexdigest()
    if (
        dry.get("schema") != "FirstTrustworthyFullShortPrivateDryRunV2"
        or dry.get("version") != 2 or dry.get("status") != "PASS"
        or dry.get("pass") is not True or dry.get("source_head") != final_head
        or dry.get("project_id_sha256") != expected_project_sha
        or dry.get("workflow_status") != "completed"
        or dry.get("completion_goal_outcome")
        != "SHORT_WORKFLOW_COMPLETED_AND_FINAL_REVIEW_ACCEPTED"
        or dry.get("all_required_stage_roles_completed") is not True
        or dry.get("all_dispatches_locally_closed") is not True
        or dry.get("isolated_gate_evidence_persisted") is not True
        or dry.get("isolated_evidence_manifest")
        != artifact.get("isolated_evidence_manifest")
        or dry.get("dry_run_artifacts_cannot_be_mistaken_for_real_output") is not True
        or not _FULL_SHORT_REQUIRED_GATE_ROLES.issubset(
            set(dry.get("completed_stage_roles") or [])
        )
        or dry.get("runtime_authority_sha256")
        != authorized_runtime_authority_sha256
        or dry.get("workload_sha256") != authorized_workload_sha256
        or not _is_sha256(dry.get("completion_receipt_sha256"))
        or not _is_sha256(dry.get("final_artifact_sha256"))
    ):
        raise OneRoundCampaignError("MANDATORY_DRY_RUN_GATE_FAILED")
    for counter in (
        "real_credential_lookup_count", "real_provider_client_creation_count",
        "real_provider_request_attempts", "real_http_post_attempts",
        "real_network_calls", "real_model_calls", "paid_calls",
    ):
        if dry.get(counter) != 0:
            raise OneRoundCampaignError("MANDATORY_DRY_RUN_GATE_FAILED")
    receipts = manifest.get("receipts")
    bindings = manifest.get("authority_bindings")
    actions = manifest.get("external_actions")
    expected_receipt_keys = {
        "completion", "terminal_verification", "final_artifact", "chapter",
        "story_state", "canon", "ready", "project_mutation_journal",
        "maintenance_receipts", "maintenance_model_receipt",
        "maintenance_output",
        "stage_artifacts",
        "base_story_state", "project", "constraints", "quality_checkpoint",
        "narrative_integrity", "canonical_authorization",
        "authorization_policy", "authorization_public_bindings",
        "runtime_journal", "replay_proof", "control_store",
        "capacity_admission_receipts", "capture_anchors",
        "provider_response_captures",
    }
    expected_binding_keys = {
        "completion_receipt_sha256", "terminal_verification_sha256",
        "final_artifact_sha256", "chapter_sha256", "story_state_sha256",
        "canon_sha256", "ready_receipt_sha256",
        "project_mutation_journal_sha256",
        "maintenance_artifact_receipt_sha256",
        "required_stage_artifacts_sha256",
        "runtime_authority_sha256", "workload_sha256",
        "project_json_sha256", "constraints_sha256",
        "quality_checkpoint_sha256", "narrative_integrity_sha256",
    }
    maintenance_authority = manifest.get("maintenance_authority")
    if (
        manifest.get("schema") != "FullShortIsolatedDryRunEvidenceManifestV2"
        or manifest.get("version") != 2
        or manifest.get("source_head") != final_head
        or manifest.get("project_id_sha256") != expected_project_sha
        or manifest.get("execution_id") != DRY_EXECUTION_ID
        or manifest.get("execution_id_sha256")
        != hashlib.sha256(DRY_EXECUTION_ID.encode("utf-8")).hexdigest()
        or not isinstance(manifest.get("durable_store"), Mapping)
        or manifest.get("private_isolated_evidence") is not True
        or not isinstance(receipts, Mapping)
        or set(receipts) != expected_receipt_keys
        or not isinstance(bindings, Mapping)
        or set(bindings) != expected_binding_keys
        or any(not _is_sha256(value) for value in bindings.values())
        or not isinstance(maintenance_authority, Mapping)
        or set(maintenance_authority) != {
            "base_story_state_revision", "base_story_state_sha256",
            "live_story_state_revision", "live_story_state_sha256",
            "maintenance_source_state_sha256", "source_modes",
            "normal_lane_exact", "reduction_lane_exact",
        }
        or not isinstance(actions, Mapping)
        or set(actions) != {
            "credential_lookup", "provider_client_creation",
            "provider_request", "http_post", "network", "model", "paid",
        }
        or any(value != 0 for value in actions.values())
    ):
        raise OneRoundCampaignError("MANDATORY_DRY_RUN_GATE_FAILED")
    raw_documents = [
        _raw_evidence_document_v1(
            gate_ordinal=gate_ordinal, kind="dry_run_output",
            path=dry_path, sha256=dry_sha,
        ),
        _raw_evidence_document_v1(
            gate_ordinal=gate_ordinal, kind="dry_run_isolated_manifest",
            path=manifest_path, sha256=manifest_sha,
        ),
    ]
    loaded: dict[str, tuple[dict[str, Any], Path, str]] = {}
    for name in (
        "completion", "terminal_verification", "story_state", "canon",
        "ready", "project_mutation_journal", "base_story_state", "project",
        "quality_checkpoint", "narrative_integrity",
    ):
        loaded[name] = _external_json_v1(
            receipts.get(name), repo=repo,
            reason="MANDATORY_DRY_RUN_RAW_EVIDENCE_INVALID",
        )
        value, path, digest = loaded[name]
        raw_documents.append(_raw_evidence_document_v1(
            gate_ordinal=gate_ordinal, kind=f"dry_run_{name}_receipt",
            path=path, sha256=digest,
        ))
    binary_evidence: dict[str, tuple[bytes, Path, str]] = {}
    for name in (
        "final_artifact", "chapter", "maintenance_model_receipt",
        "maintenance_output", "constraints",
    ):
        binary_evidence[name] = _external_file_bytes_v1(
            receipts.get(name), repo=repo,
            reason="MANDATORY_DRY_RUN_RAW_EVIDENCE_INVALID",
        )
        _raw, path, digest = binary_evidence[name]
        raw_documents.append(_raw_evidence_document_v1(
            gate_ordinal=gate_ordinal, kind=f"dry_run_{name}",
            path=path, sha256=digest,
        ))
    stage_references = receipts.get("stage_artifacts")
    if (
        not isinstance(stage_references, Mapping)
        or set(stage_references) != _FULL_SHORT_REQUIRED_ARTIFACTS
    ):
        raise OneRoundCampaignError("MANDATORY_DRY_RUN_GATE_FAILED")
    stage_hash_inputs = []
    stage_artifact_bytes: dict[str, bytes] = {}
    for name in sorted(_FULL_SHORT_REQUIRED_ARTIFACTS):
        raw, path, digest = _external_file_bytes_v1(
            stage_references[name], repo=repo,
            reason="MANDATORY_DRY_RUN_RAW_EVIDENCE_INVALID",
        )
        if name.endswith(".json"):
            try:
                parsed = json.loads(raw.decode("utf-8"))
            except (UnicodeError, ValueError, TypeError):
                raise OneRoundCampaignError(
                    "MANDATORY_DRY_RUN_GATE_FAILED"
                ) from None
            if not isinstance(parsed, dict):
                raise OneRoundCampaignError("MANDATORY_DRY_RUN_GATE_FAILED")
        stage_hash_inputs.append({"name": name, "sha256": digest})
        stage_artifact_bytes[name] = raw
        raw_documents.append(_raw_evidence_document_v1(
            gate_ordinal=gate_ordinal, kind=f"dry_run_stage_{name}",
            path=path, sha256=digest,
        ))
    completion = loaded["completion"][0]
    terminal = loaded["terminal_verification"][0]
    story_state = loaded["story_state"][0]
    base_story_state = loaded["base_story_state"][0]
    project_document = loaded["project"][0]
    quality_checkpoint = loaded["quality_checkpoint"][0]
    narrative_integrity = loaded["narrative_integrity"][0]
    canon = loaded["canon"][0]
    ready = loaded["ready"][0]
    journal_value = loaded["project_mutation_journal"][0]
    try:
        completion_body = dict(completion)
        completion_digest = completion_body.pop("completion_receipt_sha256")
        terminal_body = dict(terminal)
        terminal_digest = terminal_body.pop("verification_receipt_sha256")
        journal = ProjectMutationJournalV1.model_validate_json(
            json.dumps(journal_value, ensure_ascii=False)
        )
        ready_receipt = ShortCanonicalCommitReceiptV1.model_validate_json(
            json.dumps(ready, ensure_ascii=False)
        )
    except (KeyError, TypeError, ValueError):
        raise OneRoundCampaignError("MANDATORY_DRY_RUN_GATE_FAILED") from None
    maintenance_items = receipts.get("maintenance_receipts")
    if not isinstance(maintenance_items, list) or not maintenance_items:
        raise OneRoundCampaignError("MANDATORY_DRY_RUN_GATE_FAILED")
    maintenance_hash_inputs = []
    inventory_modes: set[str] = set()
    reduction_present = False
    final_bytes, _final_path, final_sha = binary_evidence["final_artifact"]
    try:
        final_manuscript = final_bytes.decode("utf-8")
    except UnicodeError:
        raise OneRoundCampaignError("MANDATORY_DRY_RUN_GATE_FAILED") from None
    base_revision = maintenance_authority.get("base_story_state_revision")
    base_authority_sha256 = maintenance_authority.get(
        "base_story_state_sha256"
    )
    maintenance_source_state_sha256 = maintenance_authority.get(
        "maintenance_source_state_sha256"
    )
    if (
        type(base_revision) is not int or base_revision < 1
        or not _is_sha256(base_authority_sha256)
        or not _is_sha256(maintenance_source_state_sha256)
    ):
        raise OneRoundCampaignError("MANDATORY_DRY_RUN_GATE_FAILED")
    base_story_data = base_story_state.get("data")
    if (
        base_story_state.get("schema")
        != "FullShortBaseStoryStateAuthoritySnapshotV1"
        or base_story_state.get("version") != 1
        or base_story_state.get("project_id_sha256") != expected_project_sha
        or base_story_state.get("revision") != base_revision
        or not isinstance(base_story_data, Mapping)
        or base_story_state.get("authority_sha256")
        != canonical_json_sha256(base_story_data)
        or base_story_state.get("authority_sha256") != base_authority_sha256
        or project_document.get("id") != EXACT_READY_PROJECT_ID
        or loaded["project"][2]
        != authorized_runtime_authority.get("project_json_sha256")
        or loaded["project"][2]
        != authorized_project_workload.get("project_json_sha256")
        or binary_evidence["constraints"][2]
        != authorized_project_workload.get("constraints_sha256")
        or project_document.get("target_words")
        != authorized_project_workload.get("target_words")
        or _json_sha256(authorized_runtime_authority)
        != authorized_runtime_authority_sha256
        or _json_sha256(authorized_project_workload)
        != authorized_workload_sha256
    ):
        raise OneRoundCampaignError("MANDATORY_DRY_RUN_GATE_FAILED")
    recomputed_maintenance_source_sha256 = WorkflowService._text_hash(
        json.dumps(
            WorkflowService._short_maintenance_state_authority(base_story_data),
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        )
    )
    if recomputed_maintenance_source_sha256 != maintenance_source_state_sha256:
        raise OneRoundCampaignError("MANDATORY_DRY_RUN_GATE_FAILED")
    if (
        authorized_runtime_authority.get("story_state_revision")
        != base_revision
        or authorized_runtime_authority.get("story_state_sha256")
        != base_authority_sha256
        or authorized_runtime_authority.get("maintenance_source_state_sha256")
        != maintenance_source_state_sha256
    ):
        raise OneRoundCampaignError("MANDATORY_DRY_RUN_GATE_FAILED")
    for index, item in enumerate(maintenance_items, 1):
        if (
            not isinstance(item, Mapping)
            or set(item) != {"kind", "evidence"}
            or item.get("kind") not in {
                "MaintenanceProposalInventoryV1", "MaintenanceReductionV1",
            }
        ):
            raise OneRoundCampaignError("MANDATORY_DRY_RUN_GATE_FAILED")
        value, path, digest = _external_json_v1(
            item.get("evidence"), repo=repo,
            reason="MANDATORY_DRY_RUN_RAW_EVIDENCE_INVALID",
        )
        try:
            if item["kind"] == "MaintenanceProposalInventoryV1":
                inventory = MaintenanceProposalInventoryV1.model_validate_json(
                    canonical_json_bytes(value)
                )
                if (
                    inventory.complete is not True
                    or inventory.coverage_gaps
                    or inventory.source_artifact_hash != final_sha
                    or inventory.base_authority_revision != base_revision
                    or inventory.base_authority_hash != base_authority_sha256
                ):
                    raise ValueError("maintenance inventory authority drift")
                inventory_modes.add(inventory.source_mode)
            else:
                validate_maintenance_reduction(
                    value, manuscript=final_manuscript,
                    source_state_sha256=maintenance_source_state_sha256,
                )
                reduction_present = True
        except (TypeError, ValueError):
            raise OneRoundCampaignError("MANDATORY_DRY_RUN_GATE_FAILED") from None
        maintenance_hash_inputs.append({"kind": item["kind"], "sha256": digest})
        raw_documents.append(_raw_evidence_document_v1(
            gate_ordinal=gate_ordinal,
            kind=f"dry_run_maintenance_authority_{index}",
            path=path, sha256=digest,
        ))
    _chapter_bytes, _chapter_path, chapter_sha = binary_evidence["chapter"]
    story_data = story_state.get("data")
    story_sha = canonical_json_sha256(story_data)
    canon_sha = loaded["canon"][2]
    ready_sha = loaded["ready"][2]
    journal_sha = loaded["project_mutation_journal"][2]
    final_bindings = completion.get("final_bindings")
    journal_artifacts = {
        item.path: item.sha256 for item in journal.artifacts
    }
    terminal_maintenance = terminal.get("maintenance") or {}
    terminal_checkpoint = terminal.get("final_checkpoint") or {}
    try:
        maintenance_model_receipt = json.loads(
            binary_evidence["maintenance_model_receipt"][0].decode("utf-8")
        )
        maintenance_output = json.loads(
            binary_evidence["maintenance_output"][0].decode("utf-8")
        )
    except (UnicodeError, ValueError, TypeError):
        raise OneRoundCampaignError("MANDATORY_DRY_RUN_GATE_FAILED") from None
    ledger, durable_documents = _validate_durable_dry_chain_v1(
        repo=repo, receipts=receipts,
        durable_binding=manifest.get("durable_store"),
        completion=completion, terminal=terminal, source_head=final_head,
        expected_project_sha256=expected_project_sha,
        authorized_runtime_authority=authorized_runtime_authority,
        authorized_project_workload=authorized_project_workload,
    )
    raw_documents.extend(
        _raw_evidence_document_v1(
            gate_ordinal=gate_ordinal, kind=f"dry_run_{kind}",
            path=path, sha256=digest,
        )
        for kind, path, digest in durable_documents
    )
    try:
        validate_short_maintenance_business_complete_v2(
            maintenance_output, expected_manuscript_sha256=final_sha,
        )
    except (TypeError, ValueError) as exc:
        raise OneRoundCampaignError("MANDATORY_DRY_RUN_GATE_FAILED") from exc
    maintenance_stage_receipts = [
        item for item in (ledger.get("completed_stage_receipts") or [])
        if item.get("role") == "maintenance"
    ]
    if len(maintenance_stage_receipts) != 1:
        raise OneRoundCampaignError("MANDATORY_DRY_RUN_GATE_FAILED")
    maintenance_stage_receipt = maintenance_stage_receipts[0]
    maintenance_attempts = [
        item for item in (ledger.get("attempts") or [])
        if item.get("physical_attempt_id")
        == maintenance_stage_receipt.get("accepted_physical_attempt_id")
    ]
    model_body = maintenance_model_receipt.get("model") or {}
    if (
        maintenance_stage_receipt.get("output_sha256")
        != binary_evidence["maintenance_output"][2]
        or maintenance_stage_receipt.get("receipt_sha256")
        != binary_evidence["maintenance_model_receipt"][2]
        or len(maintenance_attempts) != 1
        or maintenance_attempts[0].get("state") != "LOCAL_STAGE_COMPLETE"
        or maintenance_attempts[0].get("bound_role") != "maintenance"
        or not _is_sha256(maintenance_attempts[0].get(
            "provider_protocol_capture_receipt_sha256"
        ))
        or model_body.get("role") != "maintenance"
        or hashlib.sha256(
            str(model_body.get("provider_id") or "").encode("utf-8")
        ).hexdigest() != maintenance_attempts[0].get("provider_id_sha256")
        or hashlib.sha256(
            str(model_body.get("model_id") or "").encode("utf-8")
        ).hexdigest() != maintenance_attempts[0].get("model_id_sha256")
        or model_body.get("route_fingerprint")
        != maintenance_attempts[0].get("route_fingerprint")
    ):
        raise OneRoundCampaignError("MANDATORY_DRY_RUN_GATE_FAILED")
    normal_lane_exact = bool(
        "normal" in inventory_modes
        and isinstance(maintenance_model_receipt, Mapping)
        and isinstance(maintenance_model_receipt.get("model"), Mapping)
        and maintenance_model_receipt["model"].get("role") == "maintenance"
        and isinstance(maintenance_output, Mapping)
    )
    output_units = proposal_units_from_candidate(
        maintenance_output, source_mode="normal",
        source_locator="gate-validation", source_attempt=1,
    )
    output_payload_hashes = sorted(item.payload_hash for item in output_units)
    normal_inventory_payload_hashes = [sorted(
        unit.payload_hash
        for unit in inventory.units
    )
        for inventory in (
            MaintenanceProposalInventoryV1.model_validate_json(
                canonical_json_bytes(value)
            )
            for item in maintenance_items
            if item["kind"] == "MaintenanceProposalInventoryV1"
            for value, _path, _digest in [_external_json_v1(
                item["evidence"], repo=repo,
                reason="MANDATORY_DRY_RUN_RAW_EVIDENCE_INVALID",
            )]
        )
        if inventory.source_mode == "normal"
    ]
    if "normal" in inventory_modes and (
        output_payload_hashes not in normal_inventory_payload_hashes
    ):
        raise OneRoundCampaignError("MANDATORY_DRY_RUN_GATE_FAILED")

    report = json.loads(stage_artifact_bytes["quality-report.json"].decode("utf-8"))
    terminal_review = report.get("terminal_review") if isinstance(report, Mapping) else None
    expected_issue_ledger = (
        issue_ledger(terminal_review.get("issues", []))
        if isinstance(terminal_review, Mapping) else None
    )
    quality_checkpoint_sha256 = loaded["quality_checkpoint"][2]
    narrative_integrity_sha256 = loaded["narrative_integrity"][2]
    narrative_integrity_reference = quality_checkpoint.get(
        "narrative_integrity"
    )
    if (
        quality_checkpoint.get("version") != 1
        or quality_checkpoint.get("manuscript_path")
        != "outputs/best-candidate.md"
        or quality_checkpoint.get("manuscript_hash") != final_sha
        or quality_checkpoint.get("terminal_reviewed_hash") != final_sha
        or quality_checkpoint.get("outcome") != "passed"
        or type(quality_checkpoint.get("best_attempt")) is not int
        or quality_checkpoint["best_attempt"] < 1
        or quality_checkpoint.get("best_attempt") != report.get("best_attempt")
        or quality_checkpoint.get("score") != report.get("best_score")
        or quality_checkpoint.get("score")
        != (terminal_review or {}).get("score")
        or quality_checkpoint.get("scoring_profile_id")
        != report.get("scoring_profile_id")
        or quality_checkpoint.get("scoring_profile_id")
        != (terminal_review or {}).get("scoring_profile_id")
        or quality_checkpoint.get("judge_signature")
        != report.get("judge_signature")
        or quality_checkpoint.get("judge_signature")
        != (terminal_review or {}).get("judge_signature")
        or quality_checkpoint.get("review") != terminal_review
        or quality_checkpoint.get("issue_ledger") != expected_issue_ledger
        or not isinstance(narrative_integrity_reference, Mapping)
        or set(narrative_integrity_reference) != {"path", "sha256"}
        or not str(narrative_integrity_reference.get("path") or "").startswith(
            "outputs/"
        )
        or narrative_integrity_reference.get("sha256")
        != narrative_integrity_sha256
        or terminal_checkpoint.get("checkpoint_sha256")
        != quality_checkpoint_sha256
        or terminal_checkpoint.get("binding_status") != "exact"
        or terminal_checkpoint.get("closure_status") != "exact"
    ):
        raise OneRoundCampaignError("MANDATORY_DRY_RUN_GATE_FAILED")

    window_inventory_payload_hashes = {
        item.payload_hash
        for inventory in (
            MaintenanceProposalInventoryV1.model_validate_json(
                canonical_json_bytes(value)
            )
            for item in maintenance_items
            if item["kind"] == "MaintenanceProposalInventoryV1"
            for value, _path, _digest in [_external_json_v1(
                item["evidence"], repo=repo,
                reason="MANDATORY_DRY_RUN_RAW_EVIDENCE_INVALID",
            )]
        )
        if inventory.source_mode == "window"
        for item in inventory.units
    }
    for item in maintenance_items:
        if item["kind"] != "MaintenanceReductionV1":
            continue
        reduction_value, _path, _digest = _external_json_v1(
            item["evidence"], repo=repo,
            reason="MANDATORY_DRY_RUN_RAW_EVIDENCE_INVALID",
        )
        reduction = validate_maintenance_reduction(
            reduction_value, manuscript=final_manuscript,
            source_state_sha256=maintenance_source_state_sha256,
        )
        reduction_hashes = {
            unit.payload_hash
            for envelope in reduction.window_envelopes
            for unit in proposal_units_from_candidate(
                candidate_from_window_envelope(envelope),
                source_mode="window", source_locator="gate-validation",
                source_attempt=1,
            )
        }
        if not reduction_hashes <= window_inventory_payload_hashes:
            raise OneRoundCampaignError("MANDATORY_DRY_RUN_GATE_FAILED")

    _validate_full_short_stage_artifacts_v1(
        artifacts=stage_artifact_bytes,
        base_story_state=base_story_state,
        project=project_document,
        final_manuscript=final_manuscript,
        chapter_bytes=_chapter_bytes,
        narrative_integrity=narrative_integrity,
    )
    if (
        not final_bytes
        or final_sha != dry["final_artifact_sha256"]
        or completion.get("schema") != "FullShortCompletionReceiptV1"
        or completion.get("outcome") != "FULL_SHORT_COMPLETED_EXACT"
        or completion_digest != domain_sha256(
            "novel-flywheel-full-short-completion-receipt-v1",
            completion_body,
        )
        or completion.get("completion_receipt_sha256")
        != dry["completion_receipt_sha256"]
        or terminal.get("schema") != "ShortCompletionVerificationV1"
        or terminal_digest != domain_sha256(
            "novel-flywheel-short-completion-verification-v1", terminal_body,
        )
        or terminal.get("completion_goal_outcome")
        != dry["completion_goal_outcome"]
        or terminal.get("workflow_final_status") != "completed"
        or terminal.get("final_manuscript_sha256") != final_sha
        or story_state.get("schema")
        != "FullShortStoryStateAuthoritySnapshotV1"
        or story_state.get("version") != 1
        or story_state.get("project_id_sha256") != expected_project_sha
        or type(story_state.get("revision")) is not int
        or story_state["revision"] < 1
        or story_state.get("authority_sha256") != story_sha
        or not isinstance(canon, dict)
        or _chapter_bytes != final_bytes
        or not isinstance(final_bindings, Mapping)
        or final_bindings.get("manuscript_sha256") != final_sha
        or final_bindings.get("chapter_sha256") != chapter_sha
        or final_bindings.get("story_state_sha256") != story_sha
        or final_bindings.get("canon_sha256") != canon_sha
        or final_bindings.get("terminal_verification_sha256") != terminal_digest
        or set(final_bindings) != {
            "manuscript_sha256", "chapter_sha256", "canon_sha256",
            "story_state_sha256", "quality_checkpoint_sha256",
            "terminal_verification_sha256",
        }
        or final_bindings.get("quality_checkpoint_sha256")
        != quality_checkpoint_sha256
        or journal.status != "committed"
        or journal.operation != "short-story"
        or journal.project_id != EXACT_READY_PROJECT_ID
        or journal.story_state is None
        or journal.expected_story_state_revision != base_revision
        or journal.story_state.expected_revision != base_revision
        or journal.story_state.target_revision != story_state["revision"]
        or journal.story_state.target_revision != base_revision + 1
        or journal.story_state.state_sha256 != story_sha
        or journal.story_state.data != story_data
        or journal_artifacts.get("manuscript/story.md") != final_sha
        or journal_artifacts.get("chapters/chapter-01.md") != chapter_sha
        or journal_artifacts.get("memory/canon.json") != canon_sha
        or journal.post_commit_gate is None
        or journal.post_commit_gate.status != "passed"
        or journal.post_commit_gate.receipt_sha256 != ready_sha
        or ready_receipt.target_revision != story_state["revision"]
        or ready_receipt.base_authority_revision != base_revision
        or ready_receipt.base_authority_hash != base_authority_sha256
        or ready_receipt.target_authority_hash != story_sha
        or ready_receipt.source_artifact_hash != final_sha
        or ready_receipt.journal_saga_id != journal.run_id
        or not WorkflowService._short_canonical_live_authority_exact(
            canon, story_data, journal.post_commit_gate.payload
            if journal.post_commit_gate is not None else {},
        )
        or terminal_maintenance.get("closure_status") != "exact"
        or terminal_maintenance.get("artifact_receipt_sha256")
        != domain_sha256(
            "novel-flywheel-short-maintenance-receipts-v1",
            maintenance_hash_inputs,
        )
        or not inventory_modes
        or not (normal_lane_exact or reduction_present)
        or maintenance_authority != {
            "base_story_state_revision": base_revision,
            "base_story_state_sha256": base_authority_sha256,
            "live_story_state_revision": story_state["revision"],
            "live_story_state_sha256": story_sha,
            "maintenance_source_state_sha256": (
                maintenance_source_state_sha256
            ),
            "source_modes": sorted(inventory_modes),
            "normal_lane_exact": normal_lane_exact,
            "reduction_lane_exact": reduction_present,
        }
        or bindings.get("required_stage_artifacts_sha256")
        != _json_sha256(stage_hash_inputs)
        or bindings != {
            "completion_receipt_sha256": completion_digest,
            "terminal_verification_sha256": terminal_digest,
            "final_artifact_sha256": final_sha,
            "chapter_sha256": chapter_sha,
            "story_state_sha256": story_sha,
            "canon_sha256": canon_sha,
            "ready_receipt_sha256": ready_sha,
            "project_mutation_journal_sha256": journal_sha,
            "maintenance_artifact_receipt_sha256": terminal_maintenance.get(
                    "artifact_receipt_sha256"
                ),
                "required_stage_artifacts_sha256": _json_sha256(
                    stage_hash_inputs
                ),
                "runtime_authority_sha256": (
                    authorized_runtime_authority_sha256
                ),
                "workload_sha256": authorized_workload_sha256,
                "project_json_sha256": loaded["project"][2],
                "constraints_sha256": binary_evidence["constraints"][2],
                "quality_checkpoint_sha256": quality_checkpoint_sha256,
                "narrative_integrity_sha256": narrative_integrity_sha256,
            }
        or manifest.get("execution_id_sha256") != hashlib.sha256(
            str(completion.get("execution_id") or "").encode("utf-8")
        ).hexdigest()
    ):
        raise OneRoundCampaignError("MANDATORY_DRY_RUN_GATE_FAILED")
    return raw_documents


def _validate_size_matrix_gate_source(
    artifact: Mapping[str, Any], *, final_head: str, repo: Path,
    gate_ordinal: int,
) -> list[dict[str, Any]]:
    expected_sizes = (13_000, 20_000, 30_000)
    _require_gate_source_shape_v1(artifact, {
        "schema", "junit_xml", "envelope_manifest",
    }, "MANDATORY_SIZE_MATRIX_GATE_FAILED")
    if artifact.get("schema") != "FullShortSizeMatrixGateSourceV2":
        raise OneRoundCampaignError("MANDATORY_SIZE_MATRIX_GATE_FAILED")
    junit_raw, junit_path, junit_sha = _external_file_bytes_v1(
        artifact.get("junit_xml"), repo=repo,
        reason="MANDATORY_SIZE_MATRIX_RAW_EVIDENCE_INVALID",
    )
    manifest, manifest_path, manifest_sha = _external_json_v1(
        artifact.get("envelope_manifest"), repo=repo,
        reason="MANDATORY_SIZE_MATRIX_RAW_EVIDENCE_INVALID",
    )
    try:
        junit_root = ElementTree.fromstring(junit_raw)
    except ElementTree.ParseError:
        raise OneRoundCampaignError("MANDATORY_SIZE_MATRIX_JUNIT_INVALID") from None
    cases = [item for item in junit_root.iter("testcase")]
    observed_sizes: list[int] = []
    for case in cases:
        name = str(case.attrib.get("name") or "")
        if "test_full_short_real_http_seam" not in name:
            continue
        if list(case):
            raise OneRoundCampaignError("MANDATORY_SIZE_MATRIX_JUNIT_INVALID")
        matched = next(
            (size for size in expected_sizes if f"[{size}]" in name), None,
        )
        if matched is None:
            raise OneRoundCampaignError("MANDATORY_SIZE_MATRIX_JUNIT_INVALID")
        observed_sizes.append(matched)
    if sorted(observed_sizes) != list(expected_sizes):
        raise OneRoundCampaignError("MANDATORY_SIZE_MATRIX_JUNIT_INVALID")
    raw_documents = [
        _raw_evidence_document_v1(
            gate_ordinal=gate_ordinal, kind="size_matrix_junit_xml",
            path=junit_path, sha256=junit_sha,
        ),
        _raw_evidence_document_v1(
            gate_ordinal=gate_ordinal, kind="size_matrix_envelope_manifest",
            path=manifest_path, sha256=manifest_sha,
        ),
    ]
    records = manifest.get("run_records")
    if (
        manifest.get("schema") != "FullShortHttpSeamEnvelopeManifestV1"
        or manifest.get("version") != 1
        or manifest.get("source_head") != final_head
        or manifest.get("test_path")
        != "tests/test_workflows.py::test_full_short_real_http_seam"
        or manifest.get("test_file_sha256")
        != _repository_file_sha256_v1(repo, "tests/test_workflows.py")
        or manifest.get("junit_xml_sha256") != junit_sha
        or not isinstance(records, list)
        or len(records) != 3
        or tuple(item.get("target_words") for item in records
                 if isinstance(item, Mapping)) != expected_sizes
    ):
        raise OneRoundCampaignError("MANDATORY_SIZE_MATRIX_GATE_FAILED")
    for target_words, record in zip(expected_sizes, records, strict=True):
        if not isinstance(record, Mapping):
            raise OneRoundCampaignError("MANDATORY_SIZE_MATRIX_GATE_FAILED")
        envelopes = record.get("provider_wire_envelopes")
        actual_han = record.get("actual_effective_han_characters")
        if (
            record.get("pytest_node_id")
            != (
                "tests/test_workflows.py::test_full_short_real_http_seam"
                f"[{target_words}]"
            )
            or record.get("status") != "passed"
            or record.get("workflow_status") != "completed"
            or type(actual_han) is not int
            or not target_words <= actual_han <= int(target_words * 1.2)
            or record.get("segmentation_behavior") != "PASS"
            or record.get("required_roles_completed") is not True
            or record.get("required_artifacts_present") is not True
            or record.get("completion_goal_outcome")
            != "SHORT_WORKFLOW_COMPLETED_AND_FINAL_REVIEW_ACCEPTED"
            or not isinstance(envelopes, list) or not envelopes
        ):
            raise OneRoundCampaignError("MANDATORY_SIZE_MATRIX_GATE_FAILED")
        for envelope in envelopes:
            if not isinstance(envelope, Mapping):
                raise OneRoundCampaignError("MANDATORY_SIZE_MATRIX_GATE_FAILED")
            input_tokens = envelope.get("estimated_input_tokens")
            output_tokens = envelope.get("requested_output_tokens")
            context_limit = envelope.get("context_limit_tokens")
            output_limit = envelope.get("max_output_tokens")
            if (
                not isinstance(envelope.get("model_name"), str)
                or not envelope["model_name"]
                or type(input_tokens) is not int or input_tokens <= 0
                or type(output_tokens) is not int or output_tokens <= 0
                or type(context_limit) is not int or context_limit <= 0
                or type(output_limit) is not int or output_limit <= 0
                or type(envelope.get("payload_bytes")) is not int
                or envelope["payload_bytes"] <= 0
                or not _is_sha256(envelope.get("payload_sha256"))
                or output_tokens > output_limit
                or input_tokens + output_tokens > context_limit
            ):
                raise OneRoundCampaignError("MANDATORY_SIZE_MATRIX_GATE_FAILED")
            payload_raw, payload_path, payload_sha = _external_file_bytes_v1(
                envelope.get("payload_evidence"), repo=repo,
                reason="MANDATORY_SIZE_MATRIX_RAW_EVIDENCE_INVALID",
            )
            if (
                len(payload_raw) != envelope["payload_bytes"]
                or payload_sha != envelope["payload_sha256"]
            ):
                raise OneRoundCampaignError("MANDATORY_SIZE_MATRIX_GATE_FAILED")
            raw_documents.append(_raw_evidence_document_v1(
                gate_ordinal=gate_ordinal,
                kind=f"size_matrix_{target_words}_provider_payload",
                path=payload_path, sha256=payload_sha,
            ))
    return raw_documents


def _validate_strict_l3_gate_source(
    artifact: Mapping[str, Any], *, final_head: str, repo: Path,
    gate_ordinal: int,
) -> tuple[str, list[str], list[dict[str, Any]]]:
    allowed = {
        "schema", "inspection_stdout_json", "baseline", "forward_risk_report",
    }
    if "split_review_report" in artifact:
        allowed.add("split_review_report")
    _require_gate_source_shape_v1(
        artifact, allowed, "MANDATORY_STRICT_L3_GATE_FAILED",
    )
    if artifact.get("schema") != "FullShortStrictL3GateSourceV2":
        raise OneRoundCampaignError("MANDATORY_STRICT_L3_GATE_FAILED")
    inspection, inspection_path, inspection_sha = _external_json_v1(
        artifact.get("inspection_stdout_json"), repo=repo,
        reason="MANDATORY_STRICT_L3_RAW_EVIDENCE_INVALID",
    )
    baseline, baseline_path, baseline_sha = _external_json_v1(
        artifact.get("baseline"), repo=repo,
        reason="MANDATORY_STRICT_L3_RAW_EVIDENCE_INVALID",
    )
    forward, forward_path, forward_sha = _external_json_v1(
        artifact.get("forward_risk_report"), repo=repo,
        reason="MANDATORY_STRICT_L3_RAW_EVIDENCE_INVALID",
    )
    core_paths = inspection.get("core_paths")
    if (
        not isinstance(core_paths, list) or not core_paths
        or not all(isinstance(item, str) and item for item in core_paths)
    ):
        raise OneRoundCampaignError("MANDATORY_STRICT_L3_GATE_FAILED")
    core_tree_sha256 = _core_review_sha256_v1(repo, core_paths)
    split_reference = artifact.get("split_review_report")
    split_review: Mapping[str, Any] | None = None
    raw_documents = [
        _raw_evidence_document_v1(
            gate_ordinal=gate_ordinal, kind="strict_l3_inspection_stdout_json",
            path=inspection_path, sha256=inspection_sha,
        ),
        _raw_evidence_document_v1(
            gate_ordinal=gate_ordinal, kind="strict_l3_baseline",
            path=baseline_path, sha256=baseline_sha,
        ),
        _raw_evidence_document_v1(
            gate_ordinal=gate_ordinal, kind="strict_l3_forward_risk_report",
            path=forward_path, sha256=forward_sha,
        ),
    ]
    if split_reference is not None:
        split_review, split_path, split_sha = _external_json_v1(
            split_reference, repo=repo,
            reason="MANDATORY_STRICT_L3_RAW_EVIDENCE_INVALID",
        )
        raw_documents.append(_raw_evidence_document_v1(
            gate_ordinal=gate_ordinal, kind="strict_l3_split_review_report",
            path=split_path, sha256=split_sha,
        ))
    if (
        inspection.get("ok") is not True
        or inspection.get("warnings") != []
        or inspection.get("blockers") != []
        or inspection.get("baseline_used") is not True
        or inspection.get("recommended_level") != "L3"
        or baseline.get("version") != 1
        or Path(str(baseline.get("repository") or "")).resolve()
        != repo.resolve(strict=True)
        or not isinstance(baseline.get("state"), Mapping)
        or forward.get("version") != 2
        or not isinstance(forward.get("constraint_traceability"), list)
        or not forward["constraint_traceability"]
        or inspection.get("forward_risk_report") != forward
        or inspection.get("split_review_report") != split_review
    ):
        raise OneRoundCampaignError("MANDATORY_STRICT_L3_GATE_FAILED")
    if split_review is not None and (
        split_review.get("version") != 1
        or split_review.get("core_tree_sha256") != core_tree_sha256
    ):
        raise OneRoundCampaignError("MANDATORY_STRICT_L3_GATE_FAILED")
    if len(core_paths) > 2 and split_review is None:
        raise OneRoundCampaignError("MANDATORY_STRICT_L3_GATE_FAILED")
    return core_tree_sha256, list(core_paths), raw_documents


def _validate_reviewer_gate_source(
    artifact: Mapping[str, Any], *, final_head: str, core_tree_sha256: str,
    repo: Path, gate_ordinal: int,
) -> tuple[str, str, set[str], list[dict[str, Any]]]:
    _require_gate_source_shape_v1(
        artifact, {"schema", "review_report"},
        "MANDATORY_REVIEW_GATE_FAILED",
    )
    if artifact.get("schema") != "FullShortArchitectureReviewGateSourceV2":
        raise OneRoundCampaignError("MANDATORY_REVIEW_GATE_FAILED")
    report, report_path, report_sha = _external_json_v1(
        artifact.get("review_report"), repo=repo,
        reason="MANDATORY_REVIEW_RAW_EVIDENCE_INVALID",
    )
    role = report.get("reviewer_role")
    identity = report.get("reviewer_agent_identity")
    identity_sha = report.get("reviewer_agent_identity_sha256")
    reviewed_files = report.get("reviewed_files")
    test_files = report.get("test_files")
    reviewed_core_paths = report.get("reviewed_core_paths")
    test_raw, test_path, test_sha = _external_file_bytes_v1(
        report.get("test_run_evidence"), repo=repo,
        reason="MANDATORY_REVIEW_RAW_EVIDENCE_INVALID",
    )
    if (
        report.get("schema") != "FullShortArchitectureReviewArtifactV2"
        or report.get("version") != 2
        or report.get("final_execution_head") != final_head
        or report.get("core_tree_sha256") != core_tree_sha256
        or report.get("status") != "ARCHITECTURE_PASS"
        or report.get("findings") != []
        or role not in _MANDATORY_REVIEW_ROLES
        or not isinstance(identity, str) or not identity.strip()
        or identity_sha != hashlib.sha256(identity.strip().encode("utf-8")).hexdigest()
        or not isinstance(reviewed_files, list) or not reviewed_files
        or not isinstance(test_files, list) or not test_files
        or not isinstance(reviewed_core_paths, list) or not reviewed_core_paths
        or not all(isinstance(item, str) and item for item in reviewed_core_paths)
        or not test_raw
    ):
        raise OneRoundCampaignError("MANDATORY_REVIEW_GATE_FAILED")
    for collection in (reviewed_files, test_files):
        for item in collection:
            if (
                not isinstance(item, Mapping)
                or set(item) != {"path", "sha256"}
                or item.get("sha256")
                != _repository_file_sha256_v1(repo, item.get("path"))
            ):
                raise OneRoundCampaignError("MANDATORY_REVIEW_GATE_FAILED")
    reviewed_paths = {item["path"] for item in reviewed_files}
    if (
        not reviewed_paths
        or not set(reviewed_core_paths).issubset(reviewed_paths)
        or any(not str(item["path"]).startswith("tests/") for item in test_files)
    ):
        raise OneRoundCampaignError("MANDATORY_REVIEW_GATE_FAILED")
    raw_documents = [
        _raw_evidence_document_v1(
            gate_ordinal=gate_ordinal, kind=f"review_{role}_report",
            path=report_path, sha256=report_sha,
        ),
        _raw_evidence_document_v1(
            gate_ordinal=gate_ordinal, kind=f"review_{role}_test_run",
            path=test_path, sha256=test_sha,
        ),
    ]
    return str(role), identity.strip(), set(reviewed_core_paths), raw_documents


def _derive_mandatory_gate_receipts_v1(
    *, artifacts: Sequence[Mapping[str, Any]], artifact_paths: Sequence[Path],
    artifact_sha256s: Sequence[str], final_head: str,
    repo: Path,
    outer_authorization_sha256: str, nested_authorization_sha256: str,
    probe_evidence_manifest_sha256: str,
    previous_journal_state_sha256: str,
    campaign_started_unix_seconds: int, now_unix_seconds: int,
    authorized_runtime_authority: Mapping[str, Any],
    authorized_project_workload: Mapping[str, Any],
    authorized_runtime_authority_sha256: str,
    authorized_workload_sha256: str,
) -> tuple[MandatoryGateReceiptsV1, str, list[dict[str, Any]]]:
    if not len(artifacts) == len(artifact_paths) == len(artifact_sha256s) == 8:
        raise OneRoundCampaignError("MANDATORY_GATE_EVIDENCE_COUNT_INVALID")
    bindings = []
    for artifact in artifacts:
        bindings.append(_require_gate_campaign_binding(
            artifact,
            outer_sha256=outer_authorization_sha256,
            nested_sha256=nested_authorization_sha256,
            probe_manifest_sha256=probe_evidence_manifest_sha256,
            previous_state_sha256=previous_journal_state_sha256,
            campaign_started_unix_seconds=campaign_started_unix_seconds,
            now_unix_seconds=now_unix_seconds,
        ))
    raw_documents = _validate_dry_run_gate_source(
        artifacts[0], final_head=final_head, repo=repo, gate_ordinal=1,
        authorized_runtime_authority=authorized_runtime_authority,
        authorized_project_workload=authorized_project_workload,
        authorized_runtime_authority_sha256=(
            authorized_runtime_authority_sha256
        ),
        authorized_workload_sha256=authorized_workload_sha256,
    )
    raw_documents.extend(_validate_size_matrix_gate_source(
        artifacts[1], final_head=final_head, repo=repo, gate_ordinal=2,
    ))
    core_tree_sha256, strict_core_paths, strict_raw_documents = _validate_strict_l3_gate_source(
        artifacts[2], final_head=final_head, repo=repo, gate_ordinal=3,
    )
    raw_documents.extend(strict_raw_documents)
    roles: set[str] = set()
    identities: set[str] = set()
    reviewed_core_paths: set[str] = set()
    for index, artifact in enumerate(artifacts[3:], 4):
        role, identity, reviewed_paths, review_raw_documents = _validate_reviewer_gate_source(
            artifact, final_head=final_head,
            core_tree_sha256=core_tree_sha256,
            repo=repo, gate_ordinal=index,
        )
        roles.add(role)
        identities.add(identity)
        reviewed_core_paths.update(reviewed_paths)
        raw_documents.extend(review_raw_documents)
    if (
        roles != _MANDATORY_REVIEW_ROLES or len(identities) != 5
        or not set(strict_core_paths).issubset(reviewed_core_paths)
    ):
        raise OneRoundCampaignError("MANDATORY_REVIEW_GATE_FAILED")

    def receipt_binding(index: int) -> dict[str, Any]:
        return {
            **bindings[index],
            "evidence_path": str(artifact_paths[index]),
            "evidence_sha256": artifact_sha256s[index],
        }

    receipts = MandatoryGateReceiptsV1(
        dry_run_receipt=canonical_json_bytes({
            "schema": "FullShortExactReadyDryRunGateReceiptV1",
            "source_schema": "FirstTrustworthyFullShortPrivateDryRunV2",
            "final_execution_head": final_head,
            "project_id": EXACT_READY_PROJECT_ID,
            "status": "PASS_EXACT_READY_TARGET",
            **receipt_binding(0),
        }),
        size_matrix_receipt=canonical_json_bytes({
            "schema": "FullShortSizeMatrixGateReceiptV1",
            "source_schema": "FullShortHttpSeamProductionLengthMatrixV1",
            "final_execution_head": final_head,
            "sizes": [13_000, 20_000, 30_000],
            "segmentation_behavior": "PASS",
            "physical_envelope_bounded": "YES",
            **receipt_binding(1),
        }),
        strict_l3_receipt=canonical_json_bytes({
            "schema": "FullShortStrictL3GateReceiptV1",
            "source_schema": "NovelDevCouncilStrictInspectionV1",
            "final_execution_head": final_head,
            "core_tree_sha256": core_tree_sha256,
            "status": "PASS", "warnings": 0, "blockers": 0,
            "new_capacity_regression_count": 0,
            "new_runtime_kernel_regression_count": 0,
            "new_authority_regression_count": 0,
            "new_model_visible_literary_regression_count": 0,
            **receipt_binding(2),
        }),
        reviewer_receipts=tuple(canonical_json_bytes({
            "schema": "FullShortArchitectureReviewGateReceiptV1",
            "source_schema": "FullShortArchitectureReviewArtifactV1",
            "final_execution_head": final_head,
            "core_tree_sha256": core_tree_sha256,
            "reviewer_role": _external_json_v1(
                artifact["review_report"], repo=repo,
                reason="MANDATORY_REVIEW_RAW_EVIDENCE_INVALID",
            )[0]["reviewer_role"],
            "reviewer_agent_identity": _external_json_v1(
                artifact["review_report"], repo=repo,
                reason="MANDATORY_REVIEW_RAW_EVIDENCE_INVALID",
            )[0]["reviewer_agent_identity"],
            "status": "ARCHITECTURE_PASS",
            **receipt_binding(index),
        }) for index, artifact in enumerate(artifacts[3:], 3)),
    )
    receipts.validate(
        final_head=final_head, core_tree_sha256=core_tree_sha256,
    )
    return receipts, core_tree_sha256, raw_documents


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=repo, text=True, encoding="utf-8",
    ).strip()


def _require_frozen_repo(repo: Path, *, head: str, branch: str) -> None:
    repo = repo.resolve(strict=True)
    if _git(repo, "rev-parse", "HEAD") != head:
        raise OneRoundCampaignError("FINAL_EXECUTION_HEAD_DRIFT")
    if _git(repo, "branch", "--show-current") != branch:
        raise OneRoundCampaignError("FINAL_EXECUTION_BRANCH_DRIFT")
    if _git(repo, "status", "--porcelain"):
        raise OneRoundCampaignError("FINAL_EXECUTION_WORKTREE_NOT_CLEAN")


def _require_external_root(repo: Path, evidence_root: Path) -> Path:
    repo = repo.resolve(strict=True)
    root = evidence_root.resolve()
    if root == repo or root.is_relative_to(repo):
        raise OneRoundCampaignError("EVIDENCE_ROOT_MUST_BE_OUTSIDE_GIT")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _require_outside_repo(repo: Path, path: Path, reason_code: str) -> Path:
    repo = repo.resolve(strict=True)
    resolved = path.resolve()
    if resolved == repo or resolved.is_relative_to(repo):
        raise OneRoundCampaignError(reason_code)
    return resolved


def _full_short_run_collision_absence_receipt_v1(
    *, repo: Path, data_dir: Path, store_root: Path, run_id: str,
    final_execution_head: str, authorization_sha256: str,
    expected_store_root_sha256: str,
) -> dict[str, Any]:
    """Read only every durable identity that can make ``run_id`` non-fresh."""

    if not run_id or not _is_sha256(authorization_sha256):
        raise OneRoundCampaignError("FULL_SHORT_RUN_COLLISION_CHECK_INVALID")
    resolved_store = _require_outside_repo(
        repo, store_root, "FULL_SHORT_STORE_ROOT_INSIDE_GIT",
    )
    store_root_sha256 = hashlib.sha256(
        str(resolved_store).encode("utf-8")
    ).hexdigest()
    if store_root_sha256 != expected_store_root_sha256:
        raise OneRoundCampaignError("FULL_SHORT_STORE_ROOT_BINDING_DRIFT")

    storage_key = domain_sha256(
        "full-short-execution-storage-key-v1", run_id,
    )
    exact_paths = {
        kind: resolved_store / f"{storage_key}.{kind}.json"
        for kind in ("permission", "approval", "nonce", "ledger", "completion")
    }
    exact_paths["runtime_journal"] = (
        resolved_store / f"{run_id}.runtime-journal-v1.json"
    )
    exact_path_state = {
        kind: {
            "path_sha256": hashlib.sha256(str(path).encode("utf-8")).hexdigest(),
            "absent": not path.exists(),
        }
        for kind, path in sorted(exact_paths.items())
    }
    if not all(item["absent"] for item in exact_path_state.values()):
        raise OneRoundCampaignError("FULL_SHORT_RUN_ID_COLLISION_DETECTED")

    scanned_paths: list[str] = []
    if resolved_store.exists():
        if not resolved_store.is_dir():
            raise OneRoundCampaignError("FULL_SHORT_STORE_SCAN_FAILED")
        try:
            for path in sorted(resolved_store.rglob("*.json")):
                resolved = path.resolve(strict=True)
                if not resolved.is_relative_to(resolved_store):
                    raise OneRoundCampaignError("FULL_SHORT_STORE_SCAN_FAILED")
                raw = resolved.read_bytes()
                scanned_paths.append(
                    hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()
                )
                if run_id.encode("utf-8") in raw:
                    raise OneRoundCampaignError(
                        "FULL_SHORT_RUN_ID_COLLISION_DETECTED"
                    )
        except OneRoundCampaignError:
            raise
        except OSError:
            raise OneRoundCampaignError("FULL_SHORT_STORE_SCAN_FAILED") from None

    try:
        database_path = (data_dir.resolve(strict=True) / "app.db").resolve(
            strict=True
        )
        connection = sqlite3.connect(
            database_path.as_uri() + "?mode=ro", uri=True,
        )
        connection.execute("PRAGMA query_only=ON")
        tables = [
            str(row[0]) for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        if "runs" not in tables:
            raise OneRoundCampaignError("FULL_SHORT_RUN_DATABASE_INVALID")
        locators: list[dict[str, str]] = []
        for table in tables:
            quoted_table = table.replace('"', '""')
            columns = [
                str(row[1]) for row in connection.execute(
                    f'PRAGMA table_info("{quoted_table}")'
                )
            ]
            candidate_columns = {
                column for column in columns
                if column == "execution_id" or column.endswith("_run_id")
            }
            if table in {"runs", "skill_executions"} and "id" in columns:
                candidate_columns.add("id")
            for column in sorted(candidate_columns):
                quoted_column = column.replace('"', '""')
                count = int(connection.execute(
                    f'SELECT COUNT(*) FROM "{quoted_table}" '
                    f'WHERE "{quoted_column}"=?',
                    (run_id,),
                ).fetchone()[0])
                if count:
                    raise OneRoundCampaignError(
                        "FULL_SHORT_RUN_ID_COLLISION_DETECTED"
                    )
                locators.append({"table": table, "column": column})
    except OneRoundCampaignError:
        raise
    except (OSError, sqlite3.Error):
        raise OneRoundCampaignError("FULL_SHORT_RUN_DATABASE_INVALID") from None
    finally:
        if "connection" in locals():
            connection.close()

    return {
        "schema": "FullShortRunCollisionAbsenceReceiptV1",
        "version": 1,
        "authorization_sha256": authorization_sha256,
        "final_execution_head": final_execution_head,
        "run_id": run_id,
        "run_id_sha256": hashlib.sha256(run_id.encode("utf-8")).hexdigest(),
        "store_root_sha256": store_root_sha256,
        "database_path_sha256": hashlib.sha256(
            str(database_path).encode("utf-8")
        ).hexdigest(),
        "exact_artifacts": exact_path_state,
        "auxiliary_store_json_count": len(scanned_paths),
        "auxiliary_store_path_manifest_sha256": _json_sha256(scanned_paths),
        "database_run_locator_manifest_sha256": _json_sha256(locators),
        "database_run_locator_count": len(locators),
        "matching_run_state_count": 0,
        "permission_absent": True,
        "approval_absent": True,
        "nonce_absent": True,
        "ledger_absent": True,
        "completion_absent": True,
        "runtime_journal_absent": True,
        "real_execution_state_absent": True,
    }


def _require_bound_run_collision_absence_v1(
    materialized: MaterializedCampaignV1, *, repo: Path, data_dir: Path,
    store_root: Path, run_id: str, journal: CampaignJournalV1,
) -> tuple[dict[str, Any], str]:
    receipt = _full_short_run_collision_absence_receipt_v1(
        repo=repo, data_dir=data_dir, store_root=store_root, run_id=run_id,
        final_execution_head=materialized.authorization["frozen_execution"][
            "final_execution_head"
        ],
        authorization_sha256=materialized.authorization_sha256,
        expected_store_root_sha256=str(
            materialized.preprobe_full_short_policy["store_root_sha256"]
        ),
    )
    raw = canonical_json_bytes(receipt)
    digest = hashlib.sha256(raw).hexdigest()
    try:
        stored = (
            materialized.evidence_root
            / "full-short-run-collision-absence-v1.json"
        ).read_bytes()
    except OSError:
        raise OneRoundCampaignError(
            "FULL_SHORT_RUN_COLLISION_RECEIPT_MISSING"
        ) from None
    if stored != raw:
        raise OneRoundCampaignError("FULL_SHORT_RUN_COLLISION_RECEIPT_DRIFT")
    journal.load()
    bound = 0
    for path in journal._paths():
        body = json.loads(path.read_text(encoding="utf-8"))
        if body.get("evidence", {}).get(
            "full_short_run_collision_absence_receipt_sha256"
        ) == digest:
            bound += 1
    if bound < 1:
        raise OneRoundCampaignError("FULL_SHORT_RUN_COLLISION_RECEIPT_UNBOUND")
    return receipt, digest


def _exclusive_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise OneRoundCampaignError("EXTERNAL_EVIDENCE_ALREADY_EXISTS") from None
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            path.unlink(missing_ok=True)
        finally:
            raise


class CampaignJournalV1:
    """Append-only, hash-chained phase journal."""

    def __init__(
        self, root: Path, authorization_sha256: str, sealing_key: bytes,
    ) -> None:
        if len(sealing_key) < 32:
            raise OneRoundCampaignError("CAMPAIGN_JOURNAL_KEY_INVALID")
        self.root = root
        self.authorization_sha256 = authorization_sha256
        self.sealing_key = sealing_key

    def _paths(self) -> list[Path]:
        return sorted(self.root.glob("campaign-state-*.json"))

    def _bound_authorization(self) -> dict[str, Any] | None:
        path = self.root / "campaign-authorization-v1.json"
        if not path.exists():
            return None  # Legacy isolated journal fixtures have no outer file.
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != self.authorization_sha256:
            raise OneRoundCampaignError("CAMPAIGN_AUTHORIZATION_FILE_DRIFT")
        return json.loads(raw)

    def load(self) -> dict[str, Any]:
        previous = None
        latest = None
        campaign_started = None
        previous_recorded = None
        for sequence, path in enumerate(self._paths()):
            body = json.loads(path.read_text(encoding="utf-8"))
            if (
                body.get("schema") != "FullShortOneRoundCampaignStateV1"
                or body.get("version") != 1
                or body.get("sequence") != sequence
                or body.get("authorization_sha256") != self.authorization_sha256
                or body.get("previous_state_sha256") != previous
                or type(body.get("campaign_started_unix_seconds")) is not int
                or type(body.get("state_recorded_unix_seconds")) is not int
            ):
                raise OneRoundCampaignError("CAMPAIGN_JOURNAL_INVALID")
            if campaign_started is None:
                campaign_started = body["campaign_started_unix_seconds"]
            if (
                body["campaign_started_unix_seconds"] != campaign_started
                or body["state_recorded_unix_seconds"] < campaign_started
                or (
                    previous_recorded is not None
                    and body["state_recorded_unix_seconds"] < previous_recorded
                )
            ):
                raise OneRoundCampaignError("CAMPAIGN_JOURNAL_INVALID")
            claimed_hmac = body.pop("state_hmac_sha256", None)
            claimed = body.pop("state_sha256", None)
            actual = _json_sha256(body)
            body["state_sha256"] = claimed
            actual_hmac = hmac.new(
                self.sealing_key, canonical_json_bytes(body), hashlib.sha256,
            ).hexdigest()
            body["state_hmac_sha256"] = claimed_hmac
            if (
                claimed != actual
                or not hmac.compare_digest(str(claimed_hmac), actual_hmac)
                or path.read_bytes() != canonical_json_bytes(body)
            ):
                raise OneRoundCampaignError("CAMPAIGN_JOURNAL_INVALID")
            _validate_usage(body["usage"], authorization=self._bound_authorization())
            previous = claimed
            previous_recorded = body["state_recorded_unix_seconds"]
            latest = body
        if latest is None:
            raise OneRoundCampaignError("CAMPAIGN_JOURNAL_MISSING")
        return latest

    def append(
        self, phase: str, *, usage: Mapping[str, int], evidence: Mapping[str, Any],
    ) -> dict[str, Any]:
        paths = self._paths()
        previous_state = None if not paths else self.load()
        previous = None if previous_state is None else previous_state["state_sha256"]
        recorded = int(time.time())
        started = (
            recorded if previous_state is None
            else int(previous_state["campaign_started_unix_seconds"])
        )
        if recorded < started:
            raise OneRoundCampaignError("CAMPAIGN_CLOCK_ROLLBACK_DETECTED")
        materialized_usage = dict(usage)
        materialized_usage["elapsed_seconds"] = max(
            int(materialized_usage["elapsed_seconds"]), recorded - started,
        )
        body = {
            "schema": "FullShortOneRoundCampaignStateV1",
            "version": 1,
            "sequence": len(paths),
            "previous_state_sha256": previous,
            "authorization_sha256": self.authorization_sha256,
            "campaign_started_unix_seconds": started,
            "state_recorded_unix_seconds": recorded,
            "phase": phase,
            "usage": _validate_usage(materialized_usage, authorization=self._bound_authorization()),
            "evidence": dict(evidence),
        }
        body["state_sha256"] = _json_sha256(body)
        body["state_hmac_sha256"] = hmac.new(
            self.sealing_key, canonical_json_bytes(body), hashlib.sha256,
        ).hexdigest()
        _exclusive_write(
            self.root / f"campaign-state-{len(paths):04d}.json",
            canonical_json_bytes(body),
        )
        return body


def _require_campaign_time(state: Mapping[str, Any]) -> int:
    started = state.get("campaign_started_unix_seconds")
    if type(started) is not int:
        raise OneRoundCampaignError("CAMPAIGN_JOURNAL_INVALID")
    now = int(time.time())
    if now < started:
        raise OneRoundCampaignError("CAMPAIGN_CLOCK_ROLLBACK_DETECTED")
    elapsed = max(int(state["usage"]["elapsed_seconds"]), now - started)
    if elapsed > MAX_ELAPSED_SECONDS:
        raise OneRoundCampaignError("CAMPAIGN_ELAPSED_CAP_EXHAUSTED")
    return elapsed


def _zero_usage() -> dict[str, int]:
    return {
        "provider_requests": 0,
        "http_post_attempts": 0,
        "network_requests": 0,
        "model_calls": 0,
        "paid_calls": 0,
        "input_tokens": 0,
        "generated_output_tokens": 0,
        "real_full_short_executions": 0,
        "elapsed_seconds": 0,
        "metered_usd_micros": 0,
        "metered_cny_micros": 0,
    }


def _validate_usage(value: Mapping[str, int], *, authorization: Mapping[str, Any] | None = None) -> dict[str, int]:
    usage = dict(value)
    if set(usage) != set(_zero_usage()) or any(
        type(item) is not int or item < 0 for item in usage.values()
    ):
        raise OneRoundCampaignError("CAMPAIGN_USAGE_INVALID")
    caps = {
        "provider_requests": MAX_PROVIDER_REQUESTS,
        "http_post_attempts": MAX_HTTP_POST_ATTEMPTS,
        "network_requests": MAX_NETWORK_REQUESTS,
        "input_tokens": PLAN_DERIVED_MAX_INPUT_TOKENS,
        "generated_output_tokens": MAX_GENERATED_OUTPUT_TOKENS,
        "real_full_short_executions": 1,
        "elapsed_seconds": MAX_ELAPSED_SECONDS,
        "metered_usd_micros": 60_000_000,
        "metered_cny_micros": 120_000_000,
    }
    if authorization is not None and authorization.get("schema") in SUCCESSOR_SCHEMAS:
        for name in ("provider_requests", "http_post_attempts", "network_requests"):
            caps[name] = authorization["budgets"]["plan_derived_max_provider_requests"]
        caps["input_tokens"] = authorization["budgets"]["plan_derived_max_input_tokens"]
    if any(usage[name] > cap for name, cap in caps.items()):
        raise OneRoundCampaignError("CAMPAIGN_HARD_CAP_EXCEEDED")
    if (
        usage["model_calls"] > usage["provider_requests"]
        or usage["paid_calls"] > usage["provider_requests"]
    ):
        raise OneRoundCampaignError("CAMPAIGN_USAGE_ACCOUNTING_INVALID")
    return usage


def _authorization_usage(value: Mapping[str, int]) -> dict[str, int]:
    return {
        key: int(value[key]) for key in (
            "provider_requests", "http_post_attempts", "network_requests",
            "model_calls", "paid_calls", "input_tokens",
            "generated_output_tokens", "real_full_short_executions",
        )
    }


def _require_probe_fixture_manifest(
    materialized: MaterializedCampaignV1,
    fixtures: Sequence[SyntheticProbeFixture],
) -> None:
    expected = materialized.authorization["probe_campaign"]["cases"]
    if len(fixtures) != len(expected):
        raise OneRoundCampaignError("PROBE_FIXTURE_MANIFEST_DRIFT")
    for fixture, case in zip(fixtures, expected, strict=True):
        if {
            "ordinal": fixture.case.ordinal,
            "case_id": fixture.case.case_id,
            "case_sha256": fixture.case.case_sha256,
            "fixture_sha256": fixture.fixture_sha256,
            "input_envelope_sha256": fixture.case.input_envelope_sha256,
            "request_family_sha256": fixture.request_family_sha256,
            "request_sha256": fixture.request_sha256,
            "estimated_input_tokens": fixture.definition.estimated_input_tokens,
            "wire_requested_output_cap": fixture.definition.wire_requested_output_cap,
            "blocked_shape_ordinals": list(
                fixture.definition.blocked_shape_ordinals
            ),
        } != {key: case[key] for key in (
            "ordinal", "case_id", "case_sha256", "fixture_sha256",
            "input_envelope_sha256", "request_family_sha256",
            "request_sha256", "estimated_input_tokens",
            "wire_requested_output_cap", "blocked_shape_ordinals",
        )} or {
            "provider": fixture.route.provider,
            "operator": fixture.route.operator,
            "destination": fixture.route.destination,
            "protocol": fixture.route.protocol,
            "model": fixture.route.model,
            "route_fingerprint": fixture.route.route_fingerprint,
        } != {key: case["route"][key] for key in (
            "provider", "operator", "destination", "protocol", "model",
            "route_fingerprint",
        )}:
            raise OneRoundCampaignError("PROBE_FIXTURE_MANIFEST_DRIFT")


def _route_graph(public_bindings: Mapping[str, Any]) -> list[dict[str, Any]]:
    result = []
    for ordinal, route in enumerate(public_bindings.get("routes", []), 1):
        result.append({
            "ordinal": ordinal,
            "role": route["role"],
            "lane": route["lane"],
            "provider": route["provider_name"],
            "operator": route["provider_operator"],
            "destination": route["destination"],
            "protocol": route["protocol"],
            "model": route["model_name"],
            "route_fingerprint": route["route_fingerprint"],
        })
    if not result:
        raise OneRoundCampaignError("PRODUCTION_ROUTE_MODEL_GRAPH_EMPTY")
    return result


def derive_frozen_budget_v1(
    repo: Path, fixtures: Sequence[SyntheticProbeFixture],
) -> dict[str, Any]:
    """Recompute the authorized input budget from pinned committed evidence."""

    documents: dict[Path, dict[str, Any]] = {}
    digests: dict[Path, str] = {}
    for relative, expected_sha in _PINNED_BUDGET_SOURCE_SHA256S.items():
        path = repo / relative
        try:
            raw = path.read_bytes()
            value = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeError, ValueError, TypeError):
            raise OneRoundCampaignError("BUDGET_DERIVATION_SOURCE_INVALID") from None
        digest = hashlib.sha256(raw).hexdigest()
        if digest != expected_sha or not isinstance(value, dict):
            raise OneRoundCampaignError("BUDGET_DERIVATION_SOURCE_DRIFT")
        documents[relative] = value
        digests[relative] = digest

    budget = documents[_BUDGET_RECALCULATION_PATH]
    probe = documents[_PROBE_DERIVATION_PATH]
    matrix = documents[_ATTEMPT_MATRIX_PATH]
    if (
        budget.get("schema") != "FullShortCampaignInputBudgetRecalculationV2"
        or budget.get("version") != 2 or budget.get("status") != "PASS"
        or budget.get("authorization_source_sha256") != AUTHORIZATION_SOURCE_SHA256
        or probe.get("schema") != "FullShortBudgetUnblockedProbeFamilyDerivationV1"
        or probe.get("version") != 1 or probe.get("status") != "PASS"
        or matrix.get("schema") != "ExactReadyAuthoritativePhysicalAttemptMatrixV1"
        or matrix.get("version") != 1
        or matrix.get("matrix_kind") != "CURRENT_HEAD_DETERMINISTIC_PROVIDER_DISPATCH_SHAPE_UNION"
        or matrix.get("status") != "STOP_LOSS_BLOCKED"
        or matrix.get("mutually_exclusive_scenarios") is not True
        or matrix.get("project_id_sha256") != EXACT_READY_PROJECT_ID_SHA256
        or matrix.get("exact_ready_total_physical_attempt_shapes") != 183
        or matrix.get("exact_ready_proven_safe_physical_attempt_shapes") != 72
        or matrix.get("exact_ready_unproven_physical_attempt_count") != 111
        or probe.get("authoritative_matrix") != _ATTEMPT_MATRIX_PATH.as_posix()
        or probe.get("authoritative_matrix_sha256") != digests[_ATTEMPT_MATRIX_PATH]
        or probe.get("authoritative_physical_attempt_shape_count") != 183
        or probe.get("source_blocked_physical_shape_count") != 111
        or probe.get("minimum_exact_route_probe_case_count") != 8
        or probe.get("blocked_shape_coverage_count") != 111
        or probe.get("uncovered_blocked_shape_count") != 0
        or budget.get("external_action_counters") != {
            "credential_lookups": 0,
            "provider_client_creations": 0,
            "provider_requests": 0,
            "http_post_attempts": 0,
            "network_calls": 0,
            "model_calls": 0,
            "paid_calls": 0,
            "real_full_short_executions": 0,
        }
    ):
        raise OneRoundCampaignError("BUDGET_DERIVATION_SCHEMA_OR_BINDING_DRIFT")

    attempts = matrix.get("attempts")
    families = probe.get("families")
    if not isinstance(attempts, list) or len(attempts) != 183:
        raise OneRoundCampaignError("BUDGET_DERIVATION_MATRIX_DRIFT")
    if not isinstance(families, list) or len(families) != 8 or len(fixtures) != 8:
        raise OneRoundCampaignError("BUDGET_DERIVATION_PROBE_DRIFT")
    fixture_input = sum(item.definition.estimated_input_tokens for item in fixtures)
    expected_families = [{
        "ordinal": item.definition.ordinal,
        "family_id": item.definition.family_id,
        "role": item.definition.role,
        "contract": item.definition.contract_name,
        "shape_count": len(item.definition.blocked_shape_ordinals),
        "provider_wire_estimated_input_tokens": item.definition.estimated_input_tokens,
        "provider_wire_requested_output_cap": item.definition.wire_requested_output_cap,
    } for item in fixtures]
    if families != expected_families or fixture_input != 186_733 or (
        probe.get("probe_input_tokens") != fixture_input
        or budget.get("MINIMUM_8_PROBE_INPUT") != fixture_input
    ):
        raise OneRoundCampaignError("BUDGET_DERIVATION_PROBE_DRIFT")

    typed = [item for item in attempts if item.get("scenario") == "TYPED_BUSINESS_RECOVERY_PATH"]
    normal = [item for item in attempts if item.get("scenario") == "NORMAL_PATH"]
    shared = [item for item in attempts if item.get("scenario") == "NORMAL_PATH+TYPED_BUSINESS_RECOVERY_PATH"]
    repeated = [item for item in typed if item.get("stage") == "review-draft-whole-semantic"]
    repeated_normal = [item for item in normal if item.get("stage") == "review-draft-whole-semantic"]
    if (
        len(typed) != 94 or len(normal) != 87 or len(shared) != 1
        or len(repeated) != 1 or len(repeated_normal) != 1
    ):
        raise OneRoundCampaignError("BUDGET_DERIVATION_MATRIX_DRIFT")
    try:
        maximum_calls = len(typed) + len(shared) + 1
        maximum_input = sum(
            int(item["provider_wire_payload_estimated_tokens"])
            for item in typed + shared
        ) + int(repeated[0]["provider_wire_payload_estimated_tokens"])
        normal_deduplicated = sum(
            int(item["provider_wire_payload_estimated_tokens"])
            for item in normal + shared
        )
        restored_normal = int(repeated_normal[0]["provider_wire_payload_estimated_tokens"])
        normal_exact = normal_deduplicated + restored_normal
    except (KeyError, TypeError, ValueError):
        raise OneRoundCampaignError("BUDGET_DERIVATION_MATRIX_DRIFT") from None
    exact = maximum_input + fixture_input
    numerator = budget.get("PLAN_DERIVED_MARGIN_NUMERATOR")
    denominator = budget.get("PLAN_DERIVED_MARGIN_DENOMINATOR")
    if type(numerator) is not int or type(denominator) is not int or denominator <= 0:
        raise OneRoundCampaignError("BUDGET_DERIVATION_EQUATION_DRIFT")
    plan_cap = (exact * numerator + denominator - 1) // denominator
    if (
        maximum_calls != budget.get("MAXIMUM_TYPED_BUSINESS_RECOVERY_PATH_PHYSICAL_CALLS")
        or maximum_input != budget.get("MAXIMUM_TYPED_BUSINESS_RECOVERY_PATH_PROVIDER_WIRE_INPUT")
        or normal_deduplicated != budget.get("NORMAL_FULL_SHORT_PROVIDER_WIRE_INPUT_WITH_DEDUPLICATED_SHAPE")
        or restored_normal != budget.get("RESTORED_DEDUPLICATED_CALL_INPUT")
        or normal_exact != budget.get("NORMAL_FULL_SHORT_PROVIDER_WIRE_INPUT_EXACT")
        or exact != budget.get("EXACT_PRE_DISPATCH_ESTIMATED_INPUT_TOKENS")
        or plan_cap != budget.get("PLAN_DERIVED_MAX_INPUT_TOKENS")
        or budget.get("NEW_ABSOLUTE_MAX_INPUT_TOKENS") != OUTER_MAX_INPUT_TOKENS
        or plan_cap > OUTER_MAX_INPUT_TOKENS
        or OUTER_MAX_INPUT_TOKENS - plan_cap != budget.get("PLAN_DERIVED_HEADROOM_BELOW_NEW_ABSOLUTE_CAP")
        or budget.get("BUDGET_GATE") != "PASS"
    ):
        raise OneRoundCampaignError("BUDGET_DERIVATION_EQUATION_DRIFT")
    identity = lambda relative: {
        "identity": relative.as_posix(), "sha256": digests[relative],
    }
    return {
        "budget_recalculation_source": identity(_BUDGET_RECALCULATION_PATH),
        "authoritative_attempt_matrix_source": identity(_ATTEMPT_MATRIX_PATH),
        "probe_family_derivation_source": identity(_PROBE_DERIVATION_PATH),
        "maximum_typed_business_recovery_path_physical_calls": maximum_calls,
        "maximum_typed_business_recovery_path_provider_wire_input": maximum_input,
        "exact_probe_fixture_input_tokens": fixture_input,
        "plan_derived_margin_numerator": numerator,
        "plan_derived_margin_denominator": denominator,
        "exact_pre_dispatch_estimated_input_tokens": exact,
        "plan_derived_max_input_tokens": plan_cap,
    }


_SHARED_USAGE_EVIDENCE_ROOT = Path(
    "docs/superpowers/reports/probe01-shared-protocol-safe-cumulative-usage-fix-successor-v1"
)


def _shared_usage_recovery_binding_v1(repo: Path) -> dict[str, Any]:
    """Bind actual committed protocol proofs; digest syntax alone is insufficient."""
    names = {
        "authoritative_usage_semantics": "authoritative-usage-semantics-v1.json",
        "exact_replay": "probe01-replay-after-fix-v1.json",
        "workload_disposition": "probe01-workload-evidence-disposition-v1.json",
        "request_zero_diff": "shared-protocol-request-zero-diff-v1.json",
        "response_regression_matrix": "shared-protocol-response-regression-matrix-v1.json",
    }
    binding: dict[str, Any] = {}
    documents = {}
    for key, name in names.items():
        relative = _SHARED_USAGE_EVIDENCE_ROOT / name
        try:
            raw = (repo / relative).read_bytes()
            document = json.loads(raw)
        except (OSError, ValueError) as exc:
            raise OneRoundCampaignError("SHARED_USAGE_PROOF_MISSING_OR_INVALID") from exc
        if not isinstance(document, dict):
            raise OneRoundCampaignError("SHARED_USAGE_PROOF_MISSING_OR_INVALID")
        binding[key] = {"identity": relative.as_posix(), "sha256": hashlib.sha256(raw).hexdigest()}
        documents[key] = document
    official = documents["authoritative_usage_semantics"]
    replay = documents["exact_replay"]
    request = documents["request_zero_diff"]
    matrix = documents["response_regression_matrix"]
    disposition = documents["workload_disposition"]
    raw_sha = "de1cdf7b6eefcab2fa28f6bab664aad159be87d1d4e152250a77e61974bef713"
    if (
        official.get("AUTHORITATIVE_CUMULATIVE_USAGE_SEMANTICS_VERIFIED") != "YES"
        or not official.get("AUTHORITATIVE_SOURCE_REFERENCES")
        or replay.get("PROBE01_EXACT_REPLAY_AFTER_FIX") != "PASS"
        or replay.get("raw_capture_sha256") != raw_sha
        or replay.get("CANONICAL_FINAL_PROVIDER_INPUT_TOKENS") != 89255
        or replay.get("CANONICAL_FINAL_PROVIDER_OUTPUT_TOKENS") != 9
        or replay.get("STOP_REASON") != "end_turn"
        or disposition.get("PROBE01_HISTORICAL_EVIDENCE_DISPOSITION") != "FRESH_REPLACEMENT_REQUIRED"
        or disposition.get("historical_http_acceptance_proven") is not False
        or disposition.get("replacement_request_identity_preparable") is not True
        or disposition.get("raw_capture_sha256") != raw_sha
        or request.get("status") != "PASS"
        or any(type(request.get(field)) is not int or request[field] != 0 for field in (
            "OUTBOUND_REQUEST_BODY_CHANGED_COUNT", "MODEL_VISIBLE_REQUEST_BYTES_CHANGED_COUNT",
            "ROUTE_BINDING_CHANGED_COUNT", "OUTPUT_CAP_CHANGED_COUNT", "REASONING_POLICY_CHANGED_COUNT",
            "REQUEST_BUILDER_SOURCE_DIFF",
        ))
        or request.get("request_count", 0) < 1
        or matrix.get("status") != "PASS"
        or matrix.get("SHARED_PROTOCOL_REGRESSION_COUNT") != 0
        or matrix.get("PRECISE_CHILD_CAUSE_LOST_TO_INCOMPLETE_TERMINAL_COUNT") != 0
        or len(matrix.get("cases", [])) < 12
        or any(case.get("status") != "PASS" for case in matrix.get("cases", []))
    ):
        raise OneRoundCampaignError("SHARED_USAGE_PROTOCOL_GATE_NOT_PASS")
    inventory = request.get("inventory", {})
    inventory_bytes = (json.dumps(inventory, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if (
        hashlib.sha256(inventory_bytes).hexdigest() != request.get("before_inventory_sha256")
        or request.get("before_inventory_sha256") != request.get("after_inventory_sha256")
        or len(inventory.get("request_rows", [])) != request.get("request_count")
    ):
        raise OneRoundCampaignError("SHARED_USAGE_REQUEST_INVENTORY_DRIFT")
    for relative, digest in inventory.get("source_hashes", {}).items():
        if relative not in {
            "src/novel_flywheel/provider_payloads.py", "src/novel_flywheel/providers/http.py",
            "src/novel_flywheel/providers/registry.py", "src/novel_flywheel/context_policy.py",
        } or hashlib.sha256((repo / relative).read_bytes()).hexdigest() != digest:
            raise OneRoundCampaignError("SHARED_USAGE_REQUEST_BUILDER_SOURCE_DRIFT")
    if len(inventory.get("source_hashes", {})) != 4:
        raise OneRoundCampaignError("SHARED_USAGE_REQUEST_BUILDER_SOURCE_DRIFT")
    adapter_ast = ast.parse((repo / "src/novel_flywheel/providers/anthropic.py").read_text(encoding="utf-8"))
    complete = next(node for node in ast.walk(adapter_ast)
                    if isinstance(node, ast.AsyncFunctionDef) and node.name == "complete")
    prefix = ast.dump(ast.Module(body=complete.body[:5], type_ignores=[]), include_attributes=False)
    if hashlib.sha256(prefix.encode()).hexdigest() != inventory.get("complete_request_prefix_ast_sha256"):
        raise OneRoundCampaignError("SHARED_USAGE_REQUEST_BUILDER_SOURCE_DRIFT")
    binding.update(raw_capture_sha256=raw_sha, probe01_disposition="FRESH_REPLACEMENT_REQUIRED")
    return binding


def _require_shared_usage_recovery_binding_v1(repo: Path, authorization: Mapping[str, Any]) -> None:
    if authorization.get("schema") in SUCCESSOR_SCHEMAS:
        try:
            builder = (build_error_hardening_binding if authorization.get("schema") == ERROR_HARDENING_SCHEMA
                else build_ping_recovery_binding)
            rebuilt = builder(repo, authorization["probe_campaign"]["cases"])
        except PingSuccessorBindingError as exc:
            raise OneRoundCampaignError(str(exc)) from None
        if authorization.get("post_message_stop_ping_recovery") != rebuilt:
            raise OneRoundCampaignError("PING_PROTOCOL_PROOF_DRIFT")
    if authorization.get("schema") == SHARED_USAGE_RECOVERY_SCHEMA:
        if authorization.get("shared_protocol_usage_recovery") != _shared_usage_recovery_binding_v1(repo):
            raise OneRoundCampaignError("SHARED_USAGE_PROTOCOL_PROOF_DRIFT")


def build_outer_authorization_v1(
    *,
    repo: Path,
    head: str,
    branch: str,
    fixtures: Sequence[SyntheticProbeFixture],
    full_short_policy: Mapping[str, Any],
    full_short_public_bindings: Mapping[str, Any],
    verification_key_id: str,
    verification_key: bytes,
    shared_protocol_usage_recovery: bool = False,
    post_message_stop_ping_recovery: bool = False,
    anthropic_error_hardening: bool = False,
) -> dict[str, Any]:
    """Derive the outer document solely from frozen, credential-free truth."""

    if len(fixtures) != 8 or not verification_key_id or len(verification_key) < 32:
        raise OneRoundCampaignError("CAMPAIGN_MATERIALIZATION_INPUT_INVALID")
    if branch != EXPECTED_BRANCH:
        raise OneRoundCampaignError("FINAL_EXECUTION_BRANCH_DRIFT")
    if full_short_policy.get("execution_head") != head or full_short_policy.get(
        "branch"
    ) != branch:
        raise OneRoundCampaignError("FULL_SHORT_POLICY_FROZEN_HEAD_DRIFT")
    if full_short_public_bindings.get("project_id") != EXACT_READY_PROJECT_ID:
        raise OneRoundCampaignError("EXACT_READY_PROJECT_DRIFT")
    derived_budget = derive_frozen_budget_v1(repo, fixtures)
    route_graph = _route_graph(full_short_public_bindings)
    route_graph_sha = _json_sha256(route_graph)
    source_ordinals = sorted({
        ordinal for fixture in fixtures
        for ordinal in fixture.definition.blocked_shape_ordinals
    })
    if len(source_ordinals) != 111:
        raise OneRoundCampaignError("BLOCKED_SHAPE_COVERAGE_DRIFT")
    probe_cases = [{
        "ordinal": fixture.case.ordinal,
        "case_id": fixture.case.case_id,
        "case_sha256": fixture.case.case_sha256,
        "route": {
            "provider": fixture.route.provider,
            "operator": fixture.route.operator,
            "destination": fixture.route.destination,
            "destination_sha256": hashlib.sha256(
                fixture.route.destination.encode("utf-8")
            ).hexdigest(),
            "protocol": fixture.route.protocol,
            "model": fixture.route.model,
            "route_fingerprint": fixture.route.route_fingerprint,
        },
        "fixture_sha256": fixture.fixture_sha256,
        "input_envelope_sha256": fixture.case.input_envelope_sha256,
        "request_family_sha256": fixture.request_family_sha256,
        "request_sha256": fixture.request_sha256,
        "estimated_input_tokens": fixture.definition.estimated_input_tokens,
        "wire_requested_output_cap": fixture.definition.wire_requested_output_cap,
        "blocked_shape_ordinals": list(fixture.definition.blocked_shape_ordinals),
    } for fixture in fixtures]
    promotion = {
        "identity": "EXACT_SIGNED_WORKLOAD_LOWER_BOUND_ONLY",
        "accept_verified_safe_lower_bound": True,
        "accept_verified_workload_shape": True,
        "accept_verified_request_output_shape": True,
        "theoretical_maximum_inference_allowed": False,
        "arbitrary_external_json_allowed": False,
        "upstream_model_name_inheritance_allowed": False,
        "exact_authorization_hash_required": True,
        "exact_frozen_head_required": True,
        "exact_current_route_required": True,
        "post_freeze_git_write_allowed": False,
    }
    runtime = full_short_public_bindings["runtime_authority"]
    ready_authority = {
        "project_id_sha256": EXACT_READY_PROJECT_ID_SHA256,
        "project_workload": full_short_public_bindings["project_workload"],
        "runtime_authority": runtime,
    }
    identity = lambda name, digest: {"identity": name, "sha256": digest}
    authorization = {
        "schema": "FullShortOneRoundBudgetUnblockedExecutionAuthorizationV1",
        "version": 1,
        "authorization_source": {
            "identity": AUTHORIZATION_SOURCE_IDENTITY,
            "sha256": AUTHORIZATION_SOURCE_SHA256,
        },
        "frozen_execution": {
            "final_execution_head": head,
            "branch": branch,
            "worktree": "CLEAN",
            "no_git_write_after_final_head_freeze": True,
        },
        "probe_campaign": {
            "schema": "FullShortEightProbeCampaignV1",
            "plan_sha256": __import__(
                "novel_flywheel.full_short_probe_campaign", fromlist=[
                    "build_probe_campaign_plan",
                ],
            ).build_probe_campaign_plan(
                [fixture.case for fixture in fixtures],
                source_blocked_shape_ordinals=source_ordinals,
            ).plan_sha256,
            "cases": probe_cases,
            "source_blocked_shape_ordinals": source_ordinals,
            "blocked_shape_coverage_count": 111,
            "uncovered_blocked_shape_count": 0,
            "limits": {
                "provider_requests": 144,
                "http_post_attempts": 144,
                "network_requests": 144,
                "input_tokens": 4_000_000,
                "generated_output_tokens": 2_000_000,
                "output_tokens_per_request": 32_000,
                "elapsed_seconds": 36_000,
            },
            "sequential": True,
            "maximum_physical_requests_per_case": 1,
            "retry_allowed": False,
            "fallback_allowed": False,
            "route_switch_allowed": False,
            "stop_on_first_dispatched_failure": True,
            "exact_response_capture_required": True,
            "raw_novel_content_egress_count": 0,
            "real_project_content_egress_count": 0,
        },
        "external_workload_evidence": {
            "schema": "ExternalWorkloadEvidenceV1",
            "verification_key": {
                "key_id": verification_key_id,
                "algorithm": "HMAC-SHA256",
                "key_sha256": hashlib.sha256(verification_key).hexdigest(),
            },
            "promotion_policy": promotion,
            "promotion_policy_sha256": _json_sha256(promotion),
        },
        "exact_ready_target": {
            "project_id": EXACT_READY_PROJECT_ID,
            "project_id_sha256": EXACT_READY_PROJECT_ID_SHA256,
            "ready_authority_sha256": _json_sha256(ready_authority),
            "required_status": "READY",
        },
        "production_bindings": {
            "route_model_graph": route_graph,
            "route_model_graph_sha256": route_graph_sha,
            "route_manifest": identity(
                "CURRENT_PRODUCTION_ROUTE_MANIFEST",
                full_short_policy["route_manifest_sha256"],
            ),
            "destination_manifest": identity(
                "CURRENT_PRODUCTION_DESTINATION_MANIFEST",
                full_short_policy["destination_manifest_sha256"],
            ),
            "runtime_kernel": identity(
                "CURRENT_RUNTIME_KERNEL",
                full_short_policy["runtime_authority_sha256"],
            ),
            "baseline_skill": identity(
                "CURRENT_BASELINE_SKILL",
                full_short_policy["style_reference_authority_sha256"],
            ),
            "segmentation_windowing_policy": identity(
                "CURRENT_SEGMENTATION_WINDOWING_POLICY",
                full_short_policy["logical_stage_plan_sha256"],
            ),
            "capacity_admission_policy": identity(
                "CURRENT_CAPACITY_ADMISSION_POLICY",
                full_short_policy["capacity_policy_registry_sha256"],
            ),
            "transport_recovery_policy": identity(
                "EXACT_REPLAY_ONLY",
                full_short_policy["transport_recovery_policy_sha256"],
            ),
            "logical_stage_recovery_policy": identity(
                "TWO_SLOT_MUTUALLY_EXCLUSIVE_TYPED_RECOVERY",
                full_short_policy["logical_stage_recovery_policy_sha256"],
            ),
            "authority_gates": identity(
                "CURRENT_STORYSTATE_CANON_READY_AUTHORITY_GATES",
                _json_sha256(ready_authority),
            ),
            "response_capture_policy": identity(
                "CURRENT_EXACT_RESPONSE_CAPTURE_POLICY",
                full_short_policy["response_capture_policy_sha256"],
            ),
            "response_replay_policy": identity(
                "CURRENT_EXACT_RESPONSE_REPLAY_POLICY",
                full_short_policy["transport_recovery_policy_sha256"],
            ),
            "full_short_canonical_authorization_schema": (
                "FullShortCanonicalAuthorizationV1"
            ),
            "post_probe_authorization_derivation": {
                "identity": (
                    "FROZEN_HEAD_VERIFIED_EXTERNAL_EVIDENCE_DERIVATION_ONLY"
                ),
                "exact_outer_authorization_sha256_required": True,
                "exact_frozen_head_required": True,
                "exact_verified_evidence_packages_required": True,
                "exact_production_route_graph_required": True,
                "exact_ready_target_required": True,
                "canonical_runtime_validator_required": True,
                "external_non_git_storage_required": True,
                "arbitrary_nested_authorization_allowed": False,
                "derivation_count_maximum": 1,
            },
        },
        "budgets": {
            **derived_budget,
            "old_absolute_max_input_tokens": 2_000_000,
            "old_campaign_input_lower_bound": 2_388_221,
            "restored_deduplicated_call_input": 16_037,
            "new_absolute_max_input_tokens": 4_000_000,
            "absolute_max_provider_requests": 144,
            "absolute_max_http_post_attempts": 144,
            "absolute_max_network_requests": 144,
            "absolute_max_generated_output_tokens": 2_000_000,
            "absolute_max_output_tokens_per_provider_request": 32_000,
            "absolute_max_elapsed_seconds": 36_000,
            "usd_hard_cap_if_reliably_meterable": 60,
            "cny_hard_cap_if_reliably_meterable": 120,
            "budget_gate": "PASS",
        },
        "scope": {
            "single_campaign": True,
            "reusable": False,
            "maximum_real_full_short_executions": 1,
            "long_execution_allowed": False,
            "route_change_allowed": False,
            "model_change_allowed": False,
            "baseline_skill_change_allowed": False,
            "skill_v3_production_cutover": False,
            "hybrid_production_cutover": False,
            "selective_production_cutover": False,
            "planning_v2_production_cutover": False,
            "whole_run_retry_allowed": False,
        },
        "execution_authorized": True,
        "named_approver": "USER_PREAUTHORIZED_BY_THIS_MASTER",
        "usage_status": "unused",
        "campaign_usage": {
            "probe_phase_status": "unused",
            "full_short_phase_status": "unused",
            "provider_requests": 0,
            "http_post_attempts": 0,
            "network_requests": 0,
            "model_calls": 0,
            "paid_calls": 0,
            "input_tokens": 0,
            "generated_output_tokens": 0,
            "real_full_short_executions": 0,
            "nonces_created": 0,
        },
    }
    if shared_protocol_usage_recovery:
        authorization.update(
            schema=SHARED_USAGE_RECOVERY_SCHEMA,
            authorization_source={"identity": SHARED_USAGE_RECOVERY_SOURCE_IDENTITY,
                                  "sha256": SHARED_USAGE_RECOVERY_SOURCE_SHA256},
            shared_protocol_usage_recovery=_shared_usage_recovery_binding_v1(repo),
        )
    if post_message_stop_ping_recovery or anthropic_error_hardening:
        if sum((shared_protocol_usage_recovery, post_message_stop_ping_recovery, anthropic_error_hardening)) != 1:
            raise OneRoundCampaignError("RECOVERY_AUTHORIZATION_MODE_CONFLICT")
        try:
            builder = build_error_hardening_binding if anthropic_error_hardening else build_ping_recovery_binding
            recovery = builder(repo, probe_cases)
        except PingSuccessorBindingError as exc:
            raise OneRoundCampaignError(str(exc)) from None
        old_authorization = json.loads((repo.resolve().parent / "full-short-shared-usage-successor-20260905-v1"
            / "campaign/campaign-authorization-v1.json").read_bytes())
        old_key = old_authorization["external_workload_evidence"]["verification_key"]
        if old_key["key_id"] == verification_key_id or old_key["key_sha256"] == hashlib.sha256(verification_key).hexdigest():
            raise OneRoundCampaignError("HISTORICAL_SIGNING_KEY_REUSE_FORBIDDEN")
        authorization.update(schema=ERROR_HARDENING_SCHEMA if anthropic_error_hardening else PING_RECOVERY_SCHEMA,
            authorization_source={"identity": ERROR_HARDENING_SOURCE_IDENTITY if anthropic_error_hardening else PING_RECOVERY_SOURCE_IDENTITY,
                "sha256": ERROR_HARDENING_SOURCE_SHA256 if anthropic_error_hardening else PING_RECOVERY_SOURCE_SHA256},
            post_message_stop_ping_recovery=recovery)
        authorization["budgets"].update(selected_budget(authorization))
    return authorization


def materialize_campaign_authorization_v1(
    *,
    repo: Path,
    evidence_root: Path,
    fixtures: Sequence[SyntheticProbeFixture],
    full_short_policy: Mapping[str, Any],
    full_short_public_bindings: Mapping[str, Any],
    verification_key_id: str,
    verification_key: bytes,
    shared_protocol_usage_recovery: bool = False,
    post_message_stop_ping_recovery: bool = False,
    anthropic_error_hardening: bool = False,
) -> MaterializedCampaignV1:
    repo = repo.resolve(strict=True)
    head = _git(repo, "rev-parse", "HEAD")
    branch = _git(repo, "branch", "--show-current")
    _require_frozen_repo(repo, head=head, branch=branch)
    root = _require_external_root(repo, evidence_root)
    authorization = build_outer_authorization_v1(
        repo=repo, head=head, branch=branch, fixtures=fixtures,
        full_short_policy=full_short_policy,
        full_short_public_bindings=full_short_public_bindings,
        verification_key_id=verification_key_id,
        verification_key=verification_key,
        shared_protocol_usage_recovery=shared_protocol_usage_recovery,
        post_message_stop_ping_recovery=post_message_stop_ping_recovery,
        anthropic_error_hardening=anthropic_error_hardening,
    )
    raw = render_full_short_one_round_budget_unblocked_execution_authorization_v1(
        authorization,
        full_short_policy=full_short_policy,
        full_short_public_bindings=full_short_public_bindings,
        verification_keys={verification_key_id: verification_key},
    )
    validated = validate_full_short_one_round_budget_unblocked_execution_authorization_v1(
        raw, expected=authorization,
        full_short_policy=full_short_policy,
        full_short_public_bindings=full_short_public_bindings,
        verification_keys={verification_key_id: verification_key},
        actual_usage=_authorization_usage(_zero_usage()),
    )
    digest = validated["authorization_sha256"]
    _exclusive_write(root / "campaign-authorization-v1.json", raw)
    for case in authorization["probe_campaign"]["cases"]:
        history = historical_by_case(authorization)
        if case["case_id"] in history:
            package = seal_historical_workload_admission_v1(proof=history[case["case_id"]],
                expected=expected_evidence(authorization, digest, case, verification_key_id), signing_key=verification_key)
            _exclusive_write(root / f"historical-admission-{case['ordinal']:02d}.json", package)
    _exclusive_write(
        root / "preprobe-full-short-policy-v1.json",
        canonical_json_bytes(dict(full_short_policy)),
    )
    _exclusive_write(
        root / "preprobe-full-short-public-bindings-v1.json",
        canonical_json_bytes(dict(full_short_public_bindings)),
    )
    CampaignJournalV1(root, digest, verification_key).append(
        "MATERIALIZED_UNUSED", usage=_zero_usage(), evidence={
            "authorization_file_sha256": digest,
            "all_probe_nonces_absent": True,
            "full_short_nonce_absent": True,
        },
    )
    return MaterializedCampaignV1(
        authorization, raw, digest, root, dict(full_short_policy),
        dict(full_short_public_bindings),
    )


def _load_canonical_json_object(path: Path, reason_code: str) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, ValueError, TypeError):
        raise OneRoundCampaignError(reason_code) from None
    if not isinstance(value, dict) or raw != canonical_json_bytes(value):
        raise OneRoundCampaignError(reason_code)
    return value


def load_materialized_campaign_v1(
    *, repo: Path, evidence_root: Path,
    verification_key_id: str, verification_key: bytes,
) -> MaterializedCampaignV1:
    """Reload and authenticate an externally materialized campaign bundle."""

    root = _require_external_root(repo, evidence_root)
    authorization_path = root / "campaign-authorization-v1.json"
    try:
        raw = authorization_path.read_bytes()
        authorization = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, ValueError, TypeError):
        raise OneRoundCampaignError("CAMPAIGN_AUTHORIZATION_FILE_INVALID") from None
    if not isinstance(authorization, dict) or raw != canonical_json_bytes(
        authorization
    ):
        raise OneRoundCampaignError("CAMPAIGN_AUTHORIZATION_FILE_INVALID")
    policy = _load_canonical_json_object(
        root / "preprobe-full-short-policy-v1.json",
        "PREPROBE_FULL_SHORT_POLICY_FILE_INVALID",
    )
    public = _load_canonical_json_object(
        root / "preprobe-full-short-public-bindings-v1.json",
        "PREPROBE_FULL_SHORT_BINDINGS_FILE_INVALID",
    )
    digest = hashlib.sha256(raw).hexdigest()
    try:
        validated = (
            validate_full_short_one_round_budget_unblocked_execution_authorization_v1(
                raw, expected=authorization, full_short_policy=policy,
                full_short_public_bindings=public,
                verification_keys={verification_key_id: verification_key},
            )
        )
    except FullShortCampaignAuthorizationError as exc:
        raise OneRoundCampaignError("CAMPAIGN_AUTHORIZATION_FILE_INVALID") from exc
    if validated["authorization_sha256"] != digest:
        raise OneRoundCampaignError("CAMPAIGN_AUTHORIZATION_FILE_INVALID")
    # Loading the HMAC chain binds these bytes to the originally materialized
    # campaign and rejects replacement bundles or a partially created root.
    CampaignJournalV1(root, digest, verification_key).load()
    _require_shared_usage_recovery_binding_v1(repo, authorization)
    return MaterializedCampaignV1(
        authorization, raw, digest, root, policy, public,
    )


def _verify_historical_admission_files(materialized: MaterializedCampaignV1, *,
    key_id: str, key: bytes) -> None:
    history = historical_by_case(materialized.authorization)
    if not history:
        return
    cases = [c for c in materialized.authorization["probe_campaign"]["cases"] if c["case_id"] in history]
    if {p.name for p in materialized.evidence_root.glob("historical-admission-*.json")} != {
        f"historical-admission-{c['ordinal']:02d}.json" for c in cases}:
        raise OneRoundCampaignError("HISTORICAL_ADMISSION_FILE_SET_INVALID")
    for c in cases:
        try:
            validate_external_workload_evidence_v1((materialized.evidence_root /
                f"historical-admission-{c['ordinal']:02d}.json").read_bytes(),
                expected=expected_evidence(materialized.authorization, materialized.authorization_sha256, c, key_id),
                verification_keys={key_id: key})
        except (OSError, ExternalWorkloadEvidenceError):
            raise OneRoundCampaignError("HISTORICAL_ADMISSION_FILE_INVALID") from None


def load_verified_probe_evidence_v1(
    materialized: MaterializedCampaignV1, *,
    verification_key_id: str, verification_key: bytes,
) -> tuple[VerifiedWorkloadEvidenceV1, ...]:
    """Reload exactly eight signed packages using only outer expectations."""

    if materialized.authorization.get("schema") in SUCCESSOR_SCHEMAS:
        history = historical_by_case(materialized.authorization)
        expected_names = {f"historical-admission-{case['ordinal']:02d}.json" if case["case_id"] in history
            else f"probe-evidence-{case['ordinal']:02d}.json" for case in materialized.authorization["probe_campaign"]["cases"]}
        observed_names = {p.name for pattern in ("probe-evidence-*.json", "historical-admission-*.json")
            for p in materialized.evidence_root.glob(pattern)}
        if expected_names != observed_names:
            raise OneRoundCampaignError("PROBE_EVIDENCE_MANIFEST_INVALID")
        verified = []
        for case in materialized.authorization["probe_campaign"]["cases"]:
            prefix = "historical-admission" if case["case_id"] in history else "probe-evidence"
            path = materialized.evidence_root / f"{prefix}-{case['ordinal']:02d}.json"
            try:
                verified.append(validate_external_workload_evidence_v1(path.read_bytes(),
                    expected=expected_evidence(materialized.authorization, materialized.authorization_sha256,
                        case, verification_key_id), verification_keys={verification_key_id: verification_key}))
            except (OSError, ExternalWorkloadEvidenceError):
                raise OneRoundCampaignError("PROBE_EVIDENCE_MANIFEST_INVALID") from None
        result = tuple(verified)
        validate_external_evidence_against_outer_v1(outer=materialized.authorization,
            outer_authorization_sha256=materialized.authorization_sha256, verified_evidence=result,
            verification_keys={verification_key_id: verification_key})
        return result

    cases = materialized.authorization["probe_campaign"]["cases"]
    paths = sorted(materialized.evidence_root.glob("probe-evidence-??.json"))
    if len(paths) != 8 or len(cases) != 8:
        raise OneRoundCampaignError("PROBE_EVIDENCE_MANIFEST_INVALID")
    verified: list[VerifiedWorkloadEvidenceV1] = []
    for index, (path, case) in enumerate(zip(paths, cases, strict=True), 1):
        if path.name != f"probe-evidence-{index:02d}.json":
            raise OneRoundCampaignError("PROBE_EVIDENCE_MANIFEST_INVALID")
        expected = ExpectedWorkloadEvidenceV1(
            authorization_sha256=materialized.authorization_sha256,
            final_execution_head=materialized.authorization[
                "frozen_execution"
            ]["final_execution_head"],
            provider=case["route"]["provider"],
            operator=case["route"]["operator"],
            destination=case["route"]["destination"],
            protocol=case["route"]["protocol"],
            model=case["route"]["model"],
            route_fingerprint_sha256=case["route"]["route_fingerprint"],
            case_id=case["case_id"], fixture_sha256=case["fixture_sha256"],
            request_family_sha256=case["request_family_sha256"],
            request_sha256=case["request_sha256"],
            input_tokens=case["estimated_input_tokens"],
            requested_output_tokens=case["wire_requested_output_cap"],
            key_id=verification_key_id,
        )
        try:
            verified.append(validate_external_workload_evidence_v1(
                path.read_bytes(), expected=expected,
                verification_keys={verification_key_id: verification_key},
            ))
        except (OSError, ExternalWorkloadEvidenceError):
            raise OneRoundCampaignError("PROBE_EVIDENCE_MANIFEST_INVALID") from None
    result = tuple(verified)
    try:
        validate_external_evidence_against_outer_v1(
            outer=materialized.authorization,
            outer_authorization_sha256=materialized.authorization_sha256,
            verified_evidence=result,
            verification_keys={verification_key_id: verification_key},
        )
    except FullShortCampaignAuthorizationError as exc:
        raise OneRoundCampaignError("PROBE_EVIDENCE_MANIFEST_INVALID") from exc
    return result


def load_post_probe_authorization_v1(
    materialized: MaterializedCampaignV1,
) -> PostProbeAuthorizationV1:
    """Reload the nested canonical bytes; outer derivation is rechecked later."""

    path = materialized.evidence_root / (
        "post-probe-full-short-authorization-v1.json"
    )
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
        policy = value["policy"]
        public = value["public_bindings"]
        validate_full_short_canonical_authorization_v1(
            raw, policy=policy, public_bindings=public,
        )
    except Exception as exc:
        # The broad boundary deliberately converts lower validation errors to a
        # fixed non-secret campaign code.  Exact outer derivation is validated
        # by record/execute phase entrypoints before any dispatch.
        raise OneRoundCampaignError(
            "POST_PROBE_AUTHORIZATION_FILE_INVALID"
        ) from exc
    return PostProbeAuthorizationV1(
        dict(policy), dict(public), raw, hashlib.sha256(raw).hexdigest(),
    )


def prepare_campaign_from_live_source_v1(
    *,
    repo: Path,
    data_dir: Path,
    evidence_root: Path,
    store_root: Path,
    logical_stage_plan: Sequence[Mapping[str, Any]],
    run_id: str,
    verification_key_id: str,
    verification_key: bytes,
    expected_final_head: str,
    shared_protocol_usage_recovery: bool = False,
    post_message_stop_ping_recovery: bool = False,
    anthropic_error_hardening: bool = False,
) -> MaterializedCampaignV1:
    """Credential-free single entry for frozen-head outer materialization.

    ``logical_stage_plan`` must come from the already completed offline exact
    plan discovery.  The collector's projection mode may expose unknown
    capacity as ineligible but cannot consume evidence, credentials, or
    dispatch.  This is exactly the source truth needed before probes.
    """

    repo = repo.resolve(strict=True)
    data_dir = data_dir.resolve(strict=True)
    head = _git(repo, "rev-parse", "HEAD")
    branch = _git(repo, "branch", "--show-current")
    if head != expected_final_head:
        raise OneRoundCampaignError("FINAL_EXECUTION_HEAD_DRIFT")
    _require_frozen_repo(repo, head=head, branch=branch)
    plan = [dict(item) for item in logical_stage_plan]
    if not plan:
        raise OneRoundCampaignError("FULL_SHORT_LOGICAL_STAGE_PLAN_EMPTY")
    db = Database(data_dir / "app.db")
    registry = ProviderRegistry(db, MemorySecretStore())
    fixtures = build_synthetic_probe_fixtures(registry)
    actual, public = collect_live_bindings(
        repo=repo, data_dir=data_dir, project_id=EXACT_READY_PROJECT_ID,
        run_id=run_id, logical_stage_plan=plan,
        store_root=_require_outside_repo(
            repo, store_root, "FULL_SHORT_STORE_ROOT_INSIDE_GIT"
        ),
        outer_authorization_projection=True,
    )
    if actual.get("external_action_counters") != {
        "credential_lookup": 0,
        "provider_client_creation": 0,
        "provider_request": 0,
        "http_post": 0,
        "network": 0,
        "model": 0,
        "paid": 0,
    }:
        raise OneRoundCampaignError("PREPARATION_EXTERNAL_ACTION_DETECTED")
    expected_calls = len(plan)
    max_attempts = int(
        LOGICAL_STAGE_RECOVERY_POLICY_V1["max_physical_attempts_per_logical_stage"]
    )
    derived_budget = derive_frozen_budget_v1(repo, fixtures)
    hard_max_requests = derived_budget.get(
        "maximum_typed_business_recovery_path_physical_calls"
    )
    if (
        max_attempts < 1
        or type(hard_max_requests) is not int
        or expected_calls > hard_max_requests
        or hard_max_requests > MAX_PROVIDER_REQUESTS
    ):
        raise OneRoundCampaignError("FULL_SHORT_PHYSICAL_PLAN_CAP_INVALID")
    per_call_cap = max(int(item["requested_output_tokens"]) for item in plan)
    total_output_cap = sum(
        int(item["requested_output_tokens"]) * max_attempts for item in plan
    )
    # The probe outputs and Full Short share one cumulative outer cap.
    probe_output_cap = sum(
        fixture.definition.wire_requested_output_cap for fixture in fixtures
    )
    if (
        per_call_cap > MAX_OUTPUT_TOKENS_PER_REQUEST
        or total_output_cap + probe_output_cap > MAX_GENERATED_OUTPUT_TOKENS
    ):
        raise OneRoundCampaignError("FULL_SHORT_OUTPUT_CAMPAIGN_CAP_INVALID")
    required_roles = tuple(sorted({str(item["role"]) for item in plan}))
    policy = FullShortExecutionPolicyV1(
        execution_head=actual["head"], branch=actual["branch"], run_id=run_id,
        project_id_sha256=actual["project_id_sha256"],
        workload_sha256=actual["workload_sha256"],
        runtime_authority_sha256=actual["runtime_authority_sha256"],
        style_reference_authority_sha256=actual[
            "style_reference_authority_sha256"
        ],
        route_manifest_sha256=actual["route_manifest_sha256"],
        destination_manifest_sha256=actual["destination_manifest_sha256"],
        egress_policy_sha256=actual["egress_policy_sha256"],
        store_root_sha256=actual["store_root_sha256"],
        capture_attestation_public_key=actual["capture_attestation_public_key"],
        capture_attestation_public_key_sha256=actual[
            "capture_attestation_public_key_sha256"
        ],
        required_stage_roles=required_roles,
        logical_stage_plan=tuple(plan),
        expected_stage_calls=expected_calls,
        hard_max_provider_requests=hard_max_requests,
        hard_max_http_posts=hard_max_requests,
        hard_max_network_attempts=hard_max_requests,
        per_call_output_token_hard_cap=per_call_cap,
        total_output_token_hard_cap=max(
            total_output_cap,
            sum(int(item["requested_output_tokens"]) for item in plan)
            + int(LOGICAL_STAGE_RECOVERY_POLICY_V1["recovery_output_tokens"]),
        ),
        maximum_elapsed_seconds=MAX_ELAPSED_SECONDS,
    ).document()
    return materialize_campaign_authorization_v1(
        repo=repo, evidence_root=evidence_root, fixtures=fixtures,
        full_short_policy=policy, full_short_public_bindings=public,
        verification_key_id=verification_key_id,
        verification_key=verification_key,
        shared_protocol_usage_recovery=shared_protocol_usage_recovery,
        post_message_stop_ping_recovery=post_message_stop_ping_recovery,
        anthropic_error_hardening=anthropic_error_hardening,
    )


def preflight_campaign_v1(
    materialized: MaterializedCampaignV1, *, repo: Path,
    data_dir: Path, store_root: Path,
    fixtures: Sequence[SyntheticProbeFixture],
    full_short_policy: Mapping[str, Any],
    full_short_public_bindings: Mapping[str, Any],
    verification_key_id: str,
    verification_key: bytes,
) -> dict[str, Any]:
    _verify_historical_admission_files(materialized, key_id=verification_key_id, key=verification_key)
    if materialized.authorization.get("schema") in SUCCESSOR_SCHEMAS:
        if any(materialized.evidence_root.glob("probe-*")):
            raise OneRoundCampaignError("SUCCESSOR_PROBE_NONCE_OR_EVIDENCE_ALREADY_PRESENT")
    state = CampaignJournalV1(
        materialized.evidence_root, materialized.authorization_sha256,
        verification_key,
    ).load()
    if state["phase"] != "MATERIALIZED_UNUSED" or state["usage"] != _zero_usage():
        raise OneRoundCampaignError("ONE_ROUND_PREFLIGHT_REQUIRES_UNUSED_STATE")
    frozen = materialized.authorization["frozen_execution"]
    _require_frozen_repo(
        repo, head=frozen["final_execution_head"], branch=frozen["branch"],
    )
    on_disk = (
        materialized.evidence_root / "campaign-authorization-v1.json"
    ).read_bytes()
    if on_disk != materialized.authorization_raw:
        raise OneRoundCampaignError("CAMPAIGN_AUTHORIZATION_FILE_DRIFT")
    validated = validate_full_short_one_round_budget_unblocked_execution_authorization_v1(
        on_disk, expected=materialized.authorization,
        full_short_policy=full_short_policy,
        full_short_public_bindings=full_short_public_bindings,
        verification_keys={verification_key_id: verification_key},
        actual_usage=_authorization_usage(_zero_usage()),
    )
    rebuilt = build_outer_authorization_v1(
        repo=repo, head=frozen["final_execution_head"], branch=frozen["branch"],
        fixtures=fixtures, full_short_policy=full_short_policy,
        full_short_public_bindings=full_short_public_bindings,
        verification_key_id=verification_key_id,
        verification_key=verification_key,
        shared_protocol_usage_recovery=materialized.authorization.get("schema") == SHARED_USAGE_RECOVERY_SCHEMA,
        post_message_stop_ping_recovery=materialized.authorization.get("schema") == PING_RECOVERY_SCHEMA,
        anthropic_error_hardening=materialized.authorization.get("schema") == ERROR_HARDENING_SCHEMA,
    )
    if canonical_json_bytes(rebuilt) != canonical_json_bytes(
        {key: value for key, value in validated.items()
         if key != "authorization_sha256"}
    ):
        raise OneRoundCampaignError("ONE_ROUND_PREFLIGHT_SOURCE_TRUTH_DRIFT")
    journal = CampaignJournalV1(
        materialized.evidence_root, materialized.authorization_sha256,
        verification_key,
    )
    run_id = str(materialized.preprobe_full_short_policy["run_id"])
    collision_receipt = _full_short_run_collision_absence_receipt_v1(
        repo=repo, data_dir=data_dir, store_root=store_root, run_id=run_id,
        final_execution_head=frozen["final_execution_head"],
        authorization_sha256=materialized.authorization_sha256,
        expected_store_root_sha256=str(
            materialized.preprobe_full_short_policy["store_root_sha256"]
        ),
    )
    collision_raw = canonical_json_bytes(collision_receipt)
    _exclusive_write(
        materialized.evidence_root
        / "full-short-run-collision-absence-v1.json",
        collision_raw,
    )
    collision_sha256 = hashlib.sha256(collision_raw).hexdigest()
    return journal.append("PREFLIGHT_PASS", usage=_zero_usage(), evidence={
        "one_round_budget_unblocked_preflight": "PASS",
        "blocked_shape_coverage_count": 111,
        "uncovered_blocked_shape_count": 0,
        "full_short_run_collision_absence_receipt_sha256": collision_sha256,
    })


def run_probe_phase_v1(
    materialized: MaterializedCampaignV1, *, repo: Path,
    fixtures: Sequence[SyntheticProbeFixture], db: Database, store_root: Path,
    verification_key_id: str, verification_key: bytes,
    runner: Callable[..., GuardedRealCampaignResult] | None = None,
) -> GuardedRealCampaignResult:
    _require_shared_usage_recovery_binding_v1(repo, materialized.authorization)
    _verify_historical_admission_files(materialized, key_id=verification_key_id, key=verification_key)
    journal = CampaignJournalV1(
        materialized.evidence_root, materialized.authorization_sha256,
        verification_key,
    )
    state = journal.load()
    if state["phase"] != "PREFLIGHT_PASS":
        raise OneRoundCampaignError("PROBE_PHASE_NOT_ELIGIBLE")
    _require_campaign_time(state)
    frozen = materialized.authorization["frozen_execution"]
    _require_frozen_repo(
        repo, head=frozen["final_execution_head"], branch=frozen["branch"],
    )
    if (
        verification_key_id
        != materialized.authorization["external_workload_evidence"][
            "verification_key"
        ]["key_id"]
        or hashlib.sha256(verification_key).hexdigest()
        != materialized.authorization["external_workload_evidence"][
            "verification_key"
        ]["key_sha256"]
    ):
        raise OneRoundCampaignError("PROBE_VERIFICATION_KEY_DRIFT")
    _require_probe_fixture_manifest(materialized, fixtures)
    if materialized.authorization.get("schema") in SUCCESSOR_SCHEMAS:
        fixtures = tuple(f for f in fixtures if f.case.ordinal in selected_ordinals(materialized.authorization))
    _collision_receipt, collision_sha256 = (
        _require_bound_run_collision_absence_v1(
            materialized, repo=repo, data_dir=db.path.parent,
            store_root=store_root,
            run_id=str(materialized.preprobe_full_short_policy["run_id"]),
            journal=journal,
        )
    )
    started = time.monotonic()
    reserved = journal.append("PROBE_PHASE_RESERVED_NO_RESTART", usage=state["usage"], evidence={
        "automatic_retry_allowed": False,
        "automatic_fallback_allowed": False,
        "route_switch_allowed": False,
        "full_short_run_collision_absence_receipt_sha256": collision_sha256,
    })
    snapshots = 0
    latest_probe_state: dict[str, Any] = {}

    def persist(snapshot: Mapping[str, object]) -> None:
        nonlocal snapshots
        _exclusive_write(
            materialized.evidence_root / f"probe-state-{snapshots:04d}.json",
            canonical_json_bytes(dict(snapshot)),
        )
        snapshots += 1
        latest_probe_state.clear()
        latest_probe_state.update(snapshot)

    def raw_capture_persist(data: bytes, metadata: Mapping[str, Any]) -> bool:
        active = [record for record in latest_probe_state.get("records", [])
                  if record.get("case_sha256") == metadata.get("case_sha256")
                  and record.get("state") == "DISPATCH_ATTEMPTED"]
        if len(active) != 1:
            raise OneRoundCampaignError("RAW_CAPTURE_NONCE_BINDING_MISSING")
        if (metadata.get("provider_entity_sha256") != hashlib.sha256(data).hexdigest()
                or metadata.get("provider_entity_bytes") != len(data)):
            raise OneRoundCampaignError("RAW_CAPTURE_METADATA_HASH_MISMATCH")
        path = materialized.evidence_root / f"probe-protocol-input-{active[0]['ordinal']:02d}.raw"
        _exclusive_write(path, data)
        if hashlib.sha256(path.read_bytes()).digest() != hashlib.sha256(data).digest():
            raise OneRoundCampaignError("RAW_CAPTURE_DURABLE_HASH_MISMATCH")
        return True

    def capture_metadata_persist(metadata: Mapping[str, Any]) -> None:
        active = [record for record in latest_probe_state.get("records", [])
                  if record.get("case_sha256") == metadata.get("case_sha256")
                  and record.get("state") == "DISPATCH_ATTEMPTED"]
        if len(active) != 1:
            raise OneRoundCampaignError("CAPTURE_METADATA_NONCE_BINDING_MISSING")
        body = {
            "schema": "ProbeProtocolCaptureMetadataV1", **dict(metadata),
            "authorization_sha256": materialized.authorization_sha256,
            "execution_head": frozen["final_execution_head"],
            "nonce_sha256": active[0]["nonce_sha256"],
        }
        envelope = {"metadata": body, "metadata_hmac_sha256": hmac.new(
            verification_key, b"probe-protocol-capture-metadata-v1\0" + canonical_json_bytes(body),
            hashlib.sha256).hexdigest()}
        _exclusive_write(materialized.evidence_root / (
            f"probe-capture-metadata-{active[0]['ordinal']:02d}.json"), canonical_json_bytes(envelope))

    # Last fail-closed wall-clock check before the runner can construct the
    # keyring-backed registry or reserve an individual provider nonce.
    _require_campaign_time(reserved)
    _require_bound_run_collision_absence_v1(
        materialized, repo=repo, data_dir=db.path.parent,
        store_root=store_root,
        run_id=str(materialized.preprobe_full_short_policy["run_id"]),
        journal=journal,
    )

    runner_kwargs = {
        "authorization_sha256": materialized.authorization_sha256,
        "final_execution_head": frozen["final_execution_head"],
        "key_id": verification_key_id,
        "signing_key": verification_key,
        "persist": persist,
        "absolute_deadline_unix_seconds": (
            int(reserved["campaign_started_unix_seconds"])
            + MAX_ELAPSED_SECONDS
        ),
        "wall_clock": time.time,
    }
    if materialized.authorization.get("schema") in SUCCESSOR_SCHEMAS:
        from novel_flywheel.full_short_probe_campaign import CampaignLimits
        count = len(fixtures)
        runner_kwargs["selected_successor_plan"] = SelectedSuccessorProbePlan(
            cases=tuple(f.case for f in fixtures),
            source_blocked_shape_ordinals=tuple(sorted(n for f in fixtures for n in f.case.blocked_shape_ordinals)),
            limits=CampaignLimits(provider_requests=count, http_post_attempts=count, network_requests=count,
                input_tokens=materialized.authorization["budgets"]["plan_derived_max_input_tokens"] - 2_373_076,
                generated_output_tokens=sum(f.case.wire_requested_output_cap for f in fixtures)),
            forbidden_nonce_sha256s=tuple(materialized.authorization["post_message_stop_ping_recovery"]["excluded_prior_nonce_sha256s"]))
    if runner is None:
        # This is the only keyring-backed probe construction site.  It is
        # reached only after the HMAC journal reservation, frozen-repository
        # revalidation, route/fixture revalidation, and absolute-deadline
        # checks above.  No importable capability token can unlock it.
        registry = ProviderRegistry(
            db, KeyringSecretStore(),
            transport_policy=SingleDispatchTransportPolicyV1.phase_b(),
        )
        result = _run_guarded_campaign_with_registry_v1(
            fixtures, registry=registry, **runner_kwargs,
            capture_metadata_persist=capture_metadata_persist,
            raw_capture_persist=raw_capture_persist,
        )
    else:
        result = runner(fixtures, db=db, **runner_kwargs)
    counters = result.campaign_state["counters"]
    actual_reported_input = sum(
        item.actual_input_tokens for item in result.verified_evidence
    )
    usage = {
        "provider_requests": int(counters["provider_requests"]),
        "http_post_attempts": int(result.transport_counters["http_post_attempts"]),
        "network_requests": int(result.transport_counters["network_requests"]),
        "model_calls": int(result.transport_counters["network_requests"]),
        "paid_calls": int(result.transport_counters["network_requests"]),
        "input_tokens": max(int(counters["input_tokens"]), actual_reported_input),
        "generated_output_tokens": int(counters["generated_output_tokens"]),
        "real_full_short_executions": 0,
        "elapsed_seconds": math.ceil(time.monotonic() - started),
        "metered_usd_micros": 0,
        "metered_cny_micros": 0,
    }
    _validate_usage(usage, authorization=materialized.authorization)
    for index, package in enumerate(result.sealed_evidence, 1):
        if materialized.authorization.get("schema") in SUCCESSOR_SCHEMAS:
            index = fixtures[index - 1].case.ordinal
        _exclusive_write(
            materialized.evidence_root / f"probe-evidence-{index:02d}.json",
            package,
        )
    _exclusive_write(
        materialized.evidence_root / "probe-terminal-state-v1.json",
        canonical_json_bytes(dict(result.campaign_state)),
    )
    all_passed = (
        len(result.verified_evidence) == len(selected_ordinals(materialized.authorization))
        and result.campaign_state.get("halt_code") is None
        and all(
            record.get("state") == "PASS_CONSUMED"
            for record in result.campaign_state["records"]
        )
    )
    journal.append(
        "PROBE_ALL_PASS" if all_passed else "TERMINAL_PROBE_FAILURE",
        usage=usage,
        evidence={
            "probe_all_required_cases_pass": "YES" if all_passed else "NO",
            "verified_evidence_count": len(result.verified_evidence),
            "promoted_evidence_provider_reported_input_tokens": actual_reported_input,
            "budget_debited_input_tokens": int(counters["input_tokens"]),
            "local_pre_dispatch_estimated_input_tokens": sum(
                fixture.definition.estimated_input_tokens
                for fixture, record in zip(fixtures, result.campaign_state["records"], strict=True)
                if str(record.get("state", "")).endswith("_CONSUMED")
            ),
            "privacy_counts": dict(result.privacy_counts),
            "cost_status": "NOT_RELIABLY_METERABLE",
        },
    )
    if not all_passed:
        raise OneRoundCampaignError("FIRST_DISPATCHED_PROBE_FAILURE")
    return result


def _rebind_policy(
    template: Mapping[str, Any], actual: Mapping[str, Any], *, remaining_seconds: int,
) -> dict[str, Any]:
    return FullShortExecutionPolicyV1(
        execution_head=actual["head"], branch=actual["branch"],
        run_id=template["run_id"],
        project_id_sha256=actual["project_id_sha256"],
        workload_sha256=actual["workload_sha256"],
        runtime_authority_sha256=actual["runtime_authority_sha256"],
        style_reference_authority_sha256=actual["style_reference_authority_sha256"],
        route_manifest_sha256=actual["route_manifest_sha256"],
        destination_manifest_sha256=actual["destination_manifest_sha256"],
        egress_policy_sha256=actual["egress_policy_sha256"],
        store_root_sha256=actual["store_root_sha256"],
        capture_attestation_public_key=actual["capture_attestation_public_key"],
        capture_attestation_public_key_sha256=actual[
            "capture_attestation_public_key_sha256"
        ],
        required_stage_roles=tuple(template["required_stage_roles"]),
        logical_stage_plan=tuple(template["logical_stage_plan"]),
        expected_stage_calls=int(template["expected_stage_calls"]),
        hard_max_provider_requests=int(template["hard_max_provider_requests"]),
        hard_max_http_posts=int(template["hard_max_http_posts"]),
        hard_max_network_attempts=int(template["hard_max_network_attempts"]),
        per_call_output_token_hard_cap=int(
            template["per_call_output_token_hard_cap"]
        ),
        total_output_token_hard_cap=int(template["total_output_token_hard_cap"]),
        maximum_elapsed_seconds=min(
            int(template["maximum_elapsed_seconds"]), remaining_seconds,
        ),
        response_capture_policy_sha256=actual["response_capture_policy_sha256"],
        monetary_cost_cap_state="UNKNOWN_NOT_SEALED",
        logical_stage_recovery_policy_sha256=actual[
            "logical_stage_recovery_policy_sha256"
        ],
        failure_architecture_identity=actual["failure_architecture_identity"],
    ).document()


def derive_post_probe_authorization_v1(
    materialized: MaterializedCampaignV1, *, repo: Path, data_dir: Path,
    store_root: Path, template_policy: Mapping[str, Any],
    verified_evidence: tuple[VerifiedWorkloadEvidenceV1, ...],
    verification_key_id: str, verification_key: bytes,
) -> PostProbeAuthorizationV1:
    _require_shared_usage_recovery_binding_v1(repo, materialized.authorization)
    journal = CampaignJournalV1(
        materialized.evidence_root, materialized.authorization_sha256,
        verification_key,
    )
    state = journal.load()
    if state["phase"] != "PROBE_ALL_PASS":
        raise OneRoundCampaignError("POST_PROBE_AUTHORIZATION_NOT_ELIGIBLE")
    frozen = materialized.authorization["frozen_execution"]
    _require_frozen_repo(
        repo, head=frozen["final_execution_head"], branch=frozen["branch"],
    )
    try:
        validate_external_evidence_against_outer_v1(
            outer=materialized.authorization,
            outer_authorization_sha256=materialized.authorization_sha256,
            verified_evidence=verified_evidence,
            verification_keys={verification_key_id: verification_key},
        )
    except FullShortCampaignAuthorizationError as exc:
        raise OneRoundCampaignError(
            "POST_PROBE_EXTERNAL_EVIDENCE_NOT_AUTHORIZED"
        ) from exc
    actual, public = collect_live_bindings(
        repo=repo, data_dir=data_dir,
        project_id=EXACT_READY_PROJECT_ID,
        run_id=str(template_policy["run_id"]),
        logical_stage_plan=list(template_policy["logical_stage_plan"]),
        store_root=_require_outside_repo(
            repo, store_root, "FULL_SHORT_STORE_ROOT_INSIDE_GIT"
        ),
        verified_external_workload_evidence=verified_evidence,
        external_workload_authorized_cases=capacity_authorized_cases(materialized.authorization),
        external_workload_authorization_sha256=materialized.authorization_sha256,
        external_workload_verification_keys={verification_key_id: verification_key},
    )
    if public.get("authorization_eligible") is not True:
        raise OneRoundCampaignError("POST_PROBE_CAPACITY_LINE_NOT_CLOSED")
    if (
        actual["runtime_authority_sha256"]
        != materialized.authorization["production_bindings"]["runtime_kernel"]["sha256"]
        or actual["style_reference_authority_sha256"]
        != materialized.authorization["production_bindings"]["baseline_skill"]["sha256"]
        or actual["destination_manifest_sha256"]
        != materialized.authorization["production_bindings"]["destination_manifest"]["sha256"]
    ):
        raise OneRoundCampaignError("POST_PROBE_FROZEN_AUTHORITY_DRIFT")
    remaining_seconds = MAX_ELAPSED_SECONDS - int(state["usage"]["elapsed_seconds"])
    if remaining_seconds <= 0:
        raise OneRoundCampaignError("CAMPAIGN_ELAPSED_CAP_EXHAUSTED")
    policy = _rebind_policy(
        template_policy, actual, remaining_seconds=remaining_seconds,
    )
    projected = dict(state["usage"])
    projected["provider_requests"] += policy["hard_max_provider_requests"]
    projected["http_post_attempts"] += policy["hard_max_http_posts"]
    projected["network_requests"] += policy["hard_max_network_attempts"]
    projected["model_calls"] += policy["hard_max_provider_requests"]
    projected["paid_calls"] += policy["hard_max_provider_requests"]
    full_short_input_bound = (
        int(materialized.authorization["budgets"][
            "exact_pre_dispatch_estimated_input_tokens"
        ])
        - sum(
            int(case["estimated_input_tokens"])
            for case in materialized.authorization["probe_campaign"]["cases"]
            if case["ordinal"] in selected_ordinals(materialized.authorization)
        )
    )
    if full_short_input_bound <= 0:
        raise OneRoundCampaignError("FULL_SHORT_INPUT_BOUND_INVALID")
    projected["input_tokens"] += full_short_input_bound
    projected["generated_output_tokens"] += policy["total_output_token_hard_cap"]
    projected["real_full_short_executions"] = 1
    projected["elapsed_seconds"] += policy["maximum_elapsed_seconds"]
    if policy["per_call_output_token_hard_cap"] > MAX_OUTPUT_TOKENS_PER_REQUEST:
        raise OneRoundCampaignError("FULL_SHORT_PER_REQUEST_OUTPUT_CAP_EXCEEDED")
    _validate_usage(projected, authorization=materialized.authorization)
    raw = render_full_short_canonical_authorization_v1(
        policy=policy, public_bindings=public,
    )
    actual_usage = _authorization_usage(state["usage"])
    validate_post_probe_full_short_authorization_derivation_v1(
        outer_raw=materialized.authorization_raw,
        expected_outer=materialized.authorization,
        nested_raw=raw,
        outer_full_short_policy=materialized.preprobe_full_short_policy,
        outer_full_short_public_bindings=(
            materialized.preprobe_full_short_public_bindings
        ),
        full_short_policy=policy,
        full_short_public_bindings=public,
        verification_keys={verification_key_id: verification_key},
        verified_evidence=verified_evidence,
        actual_usage=actual_usage,
    )
    digest = hashlib.sha256(raw).hexdigest()
    _exclusive_write(
        materialized.evidence_root / "post-probe-full-short-authorization-v1.json",
        raw,
    )
    journal.append("POST_PROBE_AUTHORIZATION_SEALED", usage=state["usage"], evidence={
        "nested_authorization_sha256": digest,
        "exact_ready_proven_safe_physical_attempt_shapes": 183,
        "exact_ready_unproven_physical_attempt_count": 0,
        "capacity_engineering_line": "CLOSED",
        "projected_campaign_usage": projected,
    })
    return PostProbeAuthorizationV1(policy, public, raw, digest)


def record_mandatory_gates_v1(
    materialized: MaterializedCampaignV1, nested: PostProbeAuthorizationV1,
    *, repo: Path,
    verified_evidence: tuple[VerifiedWorkloadEvidenceV1, ...],
    verification_key_id: str, verification_key: bytes,
    gate_evidence_paths: tuple[Path, ...],
) -> dict[str, Any]:
    journal = CampaignJournalV1(
        materialized.evidence_root, materialized.authorization_sha256,
        verification_key,
    )
    state = journal.load()
    if state["phase"] != "POST_PROBE_AUTHORIZATION_SEALED":
        raise OneRoundCampaignError("MANDATORY_GATES_NOT_ELIGIBLE")
    frozen = materialized.authorization["frozen_execution"]
    if len(gate_evidence_paths) != 8:
        raise OneRoundCampaignError("MANDATORY_GATE_EVIDENCE_COUNT_INVALID")
    artifact_documents = []
    artifact_payloads: list[tuple[str, bytes]] = []
    artifact_values: list[dict[str, Any]] = []
    artifact_paths: list[Path] = []
    artifact_sha256s: list[str] = []
    observed_paths: set[Path] = set()
    observed_hashes: set[str] = set()
    for index, source in enumerate(gate_evidence_paths, 1):
        resolved = _require_outside_repo(
            repo, source, "MANDATORY_GATE_EVIDENCE_INSIDE_GIT"
        )
        try:
            artifact_raw = resolved.read_bytes()
            modified = int(resolved.stat().st_mtime)
        except OSError:
            raise OneRoundCampaignError("MANDATORY_GATE_EVIDENCE_INVALID") from None
        actual_sha = hashlib.sha256(artifact_raw).hexdigest()
        if (
            not artifact_raw or resolved in observed_paths
            or actual_sha in observed_hashes
            or modified < int(state["campaign_started_unix_seconds"])
            or modified > int(time.time()) + 1
        ):
            raise OneRoundCampaignError("MANDATORY_GATE_EVIDENCE_INVALID")
        artifact_value = _load_canonical_gate_source(artifact_raw)
        stored_name = f"gate-source-evidence-{index:02d}.bin"
        artifact_payloads.append((stored_name, artifact_raw))
        artifact_documents.append({
            "ordinal": index, "source_path": str(resolved),
            "evidence_sha256": actual_sha, "stored_name": stored_name,
        })
        artifact_values.append(artifact_value)
        artifact_paths.append(resolved)
        artifact_sha256s.append(actual_sha)
        observed_paths.add(resolved)
        observed_hashes.add(actual_sha)
    probe_evidence_manifest_sha256 = _json_sha256(sorted(
        item.evidence_sha256 for item in verified_evidence
    ))
    receipts, core_tree_sha256, raw_evidence_documents = (
        _derive_mandatory_gate_receipts_v1(
        artifacts=artifact_values,
        artifact_paths=artifact_paths,
        artifact_sha256s=artifact_sha256s,
        final_head=frozen["final_execution_head"],
        repo=repo,
        outer_authorization_sha256=materialized.authorization_sha256,
        nested_authorization_sha256=nested.authorization_sha256,
        probe_evidence_manifest_sha256=probe_evidence_manifest_sha256,
        previous_journal_state_sha256=state["state_sha256"],
        campaign_started_unix_seconds=int(
            state["campaign_started_unix_seconds"]
        ),
        now_unix_seconds=int(time.time()),
        authorized_runtime_authority=nested.public_bindings[
            "runtime_authority"
        ],
        authorized_project_workload=nested.public_bindings[
            "project_workload"
        ],
        authorized_runtime_authority_sha256=nested.policy[
            "runtime_authority_sha256"
        ],
        authorized_workload_sha256=nested.policy["workload_sha256"],
    ))
    _require_frozen_repo(
        repo, head=frozen["final_execution_head"], branch=frozen["branch"],
    )
    try:
        validate_post_probe_full_short_authorization_derivation_v1(
            outer_raw=materialized.authorization_raw,
            expected_outer=materialized.authorization,
            nested_raw=nested.authorization_raw,
            outer_full_short_policy=materialized.preprobe_full_short_policy,
            outer_full_short_public_bindings=(
                materialized.preprobe_full_short_public_bindings
            ),
            full_short_policy=nested.policy,
            full_short_public_bindings=nested.public_bindings,
            verification_keys={verification_key_id: verification_key},
            verified_evidence=verified_evidence,
            actual_usage=_authorization_usage(state["usage"]),
        )
    except FullShortCampaignAuthorizationError as exc:
        raise OneRoundCampaignError(
            "POST_PROBE_AUTHORIZATION_DERIVATION_INVALID"
        ) from exc
    nested_path = (
        materialized.evidence_root
        / "post-probe-full-short-authorization-v1.json"
    )
    if (
        nested_path.read_bytes() != nested.authorization_raw
        or hashlib.sha256(nested.authorization_raw).hexdigest()
        != nested.authorization_sha256
    ):
        raise OneRoundCampaignError("POST_PROBE_AUTHORIZATION_FILE_DRIFT")
    for stored_name, artifact_raw in artifact_payloads:
        _exclusive_write(
            materialized.evidence_root / stored_name, artifact_raw,
        )
    gate_manifest = {
        "schema": "FullShortMandatoryGateEvidenceManifestV1",
        "outer_authorization_sha256": materialized.authorization_sha256,
        "nested_authorization_sha256": nested.authorization_sha256,
        "probe_evidence_manifest_sha256": probe_evidence_manifest_sha256,
        "previous_journal_state_sha256": state["state_sha256"],
        "final_execution_head": frozen["final_execution_head"],
        "core_tree_sha256": core_tree_sha256,
        "receipts": receipts.document(),
        "source_evidence": artifact_documents,
        "raw_evidence": raw_evidence_documents,
    }
    _exclusive_write(
        materialized.evidence_root / "mandatory-gates-manifest-v1.json",
        canonical_json_bytes(gate_manifest),
    )
    _exclusive_write(
        materialized.evidence_root / "gate-dry-run-v1.json",
        receipts.dry_run_receipt,
    )
    _exclusive_write(
        materialized.evidence_root / "gate-size-matrix-v1.json",
        receipts.size_matrix_receipt,
    )
    _exclusive_write(
        materialized.evidence_root / "gate-strict-l3-v1.json",
        receipts.strict_l3_receipt,
    )
    for index, raw in enumerate(receipts.reviewer_receipts, 1):
        _exclusive_write(
            materialized.evidence_root / f"gate-review-{index:02d}-v1.json",
            raw,
        )
    return journal.append(
        "FULL_SHORT_ELIGIBLE", usage=state["usage"], evidence={
            "mandatory_gate_manifest_sha256": _json_sha256(gate_manifest),
            "nested_authorization_sha256": nested.authorization_sha256,
            "raw_evidence_sha256s": [
                item["evidence_sha256"] for item in raw_evidence_documents
            ],
            "raw_evidence_count": len(raw_evidence_documents),
        },
    )


async def execute_one_full_short_v1(
    materialized: MaterializedCampaignV1,
    nested: PostProbeAuthorizationV1,
    *, repo: Path, data_dir: Path, store_root: Path,
    verified_evidence: tuple[VerifiedWorkloadEvidenceV1, ...],
    verification_key_id: str, verification_key: bytes,
    executor: Callable[..., Any] = execute_full_short_control_plane,
) -> dict[str, Any]:
    """Consume the sole Full Short phase; there is intentionally no retry API."""

    _require_shared_usage_recovery_binding_v1(repo, materialized.authorization)
    journal = CampaignJournalV1(
        materialized.evidence_root, materialized.authorization_sha256,
        verification_key,
    )
    state = journal.load()
    if state["phase"] != "FULL_SHORT_ELIGIBLE":
        raise OneRoundCampaignError("REAL_FULL_SHORT_NOT_ELIGIBLE_OR_CONSUMED")
    _require_campaign_time(state)
    frozen = materialized.authorization["frozen_execution"]
    _require_frozen_repo(
        repo, head=frozen["final_execution_head"], branch=frozen["branch"],
    )
    if (
        verification_key_id
        != materialized.authorization["external_workload_evidence"][
            "verification_key"
        ]["key_id"]
        or hashlib.sha256(verification_key).hexdigest()
        != materialized.authorization["external_workload_evidence"][
            "verification_key"
        ]["key_sha256"]
        or (
            materialized.evidence_root / "campaign-authorization-v1.json"
        ).read_bytes() != materialized.authorization_raw
    ):
        raise OneRoundCampaignError("FINAL_FULL_SHORT_AUTHORITY_DRIFT")
    try:
        validate_external_evidence_against_outer_v1(
            outer=materialized.authorization,
            outer_authorization_sha256=materialized.authorization_sha256,
            verified_evidence=verified_evidence,
            verification_keys={verification_key_id: verification_key},
        )
        validate_post_probe_full_short_authorization_derivation_v1(
            outer_raw=materialized.authorization_raw,
            expected_outer=materialized.authorization,
            nested_raw=nested.authorization_raw,
            outer_full_short_policy=materialized.preprobe_full_short_policy,
            outer_full_short_public_bindings=(
                materialized.preprobe_full_short_public_bindings
            ),
            full_short_policy=nested.policy,
            full_short_public_bindings=nested.public_bindings,
            verification_keys={verification_key_id: verification_key},
            verified_evidence=verified_evidence,
            actual_usage=_authorization_usage(state["usage"]),
        )
    except FullShortCampaignAuthorizationError as exc:
        raise OneRoundCampaignError("FINAL_FULL_SHORT_AUTHORITY_DRIFT") from exc
    nested_path = (
        materialized.evidence_root
        / "post-probe-full-short-authorization-v1.json"
    )
    if (
        nested_path.read_bytes() != nested.authorization_raw
        or hashlib.sha256(nested.authorization_raw).hexdigest()
        != nested.authorization_sha256
    ):
        raise OneRoundCampaignError("FINAL_FULL_SHORT_AUTHORITY_DRIFT")
    reviewer_paths = sorted(
        materialized.evidence_root.glob("gate-review-??-v1.json")
    )
    gates = MandatoryGateReceiptsV1(
        dry_run_receipt=(
            materialized.evidence_root / "gate-dry-run-v1.json"
        ).read_bytes(),
        size_matrix_receipt=(
            materialized.evidence_root / "gate-size-matrix-v1.json"
        ).read_bytes(),
        strict_l3_receipt=(
            materialized.evidence_root / "gate-strict-l3-v1.json"
        ).read_bytes(),
        reviewer_receipts=tuple(path.read_bytes() for path in reviewer_paths),
    )
    strict_body = MandatoryGateReceiptsV1._canonical(gates.strict_l3_receipt)
    gates.validate(
        final_head=frozen["final_execution_head"],
        core_tree_sha256=str(strict_body.get("core_tree_sha256") or ""),
    )
    gate_manifest = _load_canonical_json_object(
        materialized.evidence_root / "mandatory-gates-manifest-v1.json",
        "FINAL_MANDATORY_GATE_RECEIPT_DRIFT",
    )
    journal_paths = sorted(
        materialized.evidence_root.glob("campaign-state-*.json")
    )
    predecessor = json.loads(journal_paths[-2].read_text(encoding="utf-8"))
    expected_probe_manifest = _json_sha256(sorted(
        item.evidence_sha256 for item in verified_evidence
    ))
    source_documents = gate_manifest.get("source_evidence")
    raw_documents = gate_manifest.get("raw_evidence")
    if (
        gate_manifest.get("schema")
        != "FullShortMandatoryGateEvidenceManifestV1"
        or gate_manifest.get("outer_authorization_sha256")
        != materialized.authorization_sha256
        or gate_manifest.get("nested_authorization_sha256")
        != nested.authorization_sha256
        or gate_manifest.get("probe_evidence_manifest_sha256")
        != expected_probe_manifest
        or gate_manifest.get("previous_journal_state_sha256")
        != predecessor.get("state_sha256")
        or gate_manifest.get("final_execution_head")
        != frozen["final_execution_head"]
        or gate_manifest.get("receipts") != gates.document()
        or not isinstance(source_documents, list)
        or len(source_documents) != 8
        or not isinstance(raw_documents, list)
        or not raw_documents
        or state["evidence"].get("mandatory_gate_manifest_sha256")
        != _json_sha256(gate_manifest)
        or state["evidence"].get("nested_authorization_sha256")
        != nested.authorization_sha256
        or state["evidence"].get("raw_evidence_sha256s")
        != [item.get("evidence_sha256") for item in raw_documents]
        or state["evidence"].get("raw_evidence_count") != len(raw_documents)
    ):
        raise OneRoundCampaignError("FINAL_MANDATORY_GATE_RECEIPT_DRIFT")
    stored_values: list[dict[str, Any]] = []
    original_paths: list[Path] = []
    source_sha256s: list[str] = []
    for ordinal, document in enumerate(source_documents, 1):
        if not isinstance(document, Mapping) or document.get("ordinal") != ordinal:
            raise OneRoundCampaignError("FINAL_MANDATORY_GATE_RECEIPT_DRIFT")
        stored_name = document.get("stored_name")
        if stored_name != f"gate-source-evidence-{ordinal:02d}.bin":
            raise OneRoundCampaignError("FINAL_MANDATORY_GATE_RECEIPT_DRIFT")
        try:
            stored_raw = (materialized.evidence_root / stored_name).read_bytes()
        except OSError:
            raise OneRoundCampaignError(
                "FINAL_MANDATORY_GATE_RECEIPT_DRIFT"
            ) from None
        if hashlib.sha256(stored_raw).hexdigest() != document.get(
            "evidence_sha256"
        ):
            raise OneRoundCampaignError("FINAL_MANDATORY_GATE_RECEIPT_DRIFT")
        stored_values.append(_load_canonical_gate_source(stored_raw))
        original_paths.append(Path(str(document.get("source_path") or "")))
        source_sha256s.append(str(document.get("evidence_sha256") or ""))
    rederived, rederived_core_tree, rederived_raw_documents = (
        _derive_mandatory_gate_receipts_v1(
            artifacts=stored_values,
            artifact_paths=original_paths,
            artifact_sha256s=source_sha256s,
            final_head=frozen["final_execution_head"],
            repo=repo,
            outer_authorization_sha256=materialized.authorization_sha256,
            nested_authorization_sha256=nested.authorization_sha256,
            probe_evidence_manifest_sha256=expected_probe_manifest,
            previous_journal_state_sha256=str(
                gate_manifest["previous_journal_state_sha256"]
            ),
            campaign_started_unix_seconds=int(
                state["campaign_started_unix_seconds"]
            ),
            now_unix_seconds=int(time.time()),
            authorized_runtime_authority=nested.public_bindings[
                "runtime_authority"
            ],
            authorized_project_workload=nested.public_bindings[
                "project_workload"
            ],
            authorized_runtime_authority_sha256=nested.policy[
                "runtime_authority_sha256"
            ],
            authorized_workload_sha256=nested.policy["workload_sha256"],
        )
    )
    if (
        rederived.document() != gates.document()
        or rederived_core_tree != gate_manifest.get("core_tree_sha256")
        or rederived_raw_documents != raw_documents
    ):
        raise OneRoundCampaignError("FINAL_MANDATORY_GATE_RECEIPT_DRIFT")
    projected = state["evidence"].get("projected_campaign_usage")
    # The projection is sealed on the preceding journal record, not copied to
    # the gate record. Re-read that exact predecessor and validate it.
    projected = predecessor["evidence"].get("projected_campaign_usage")
    if not isinstance(projected, Mapping):
        raise OneRoundCampaignError("PROJECTED_CAMPAIGN_USAGE_MISSING")
    _validate_usage(projected, authorization=materialized.authorization)
    run_id = str(nested.policy.get("run_id") or "")
    if (
        run_id != materialized.preprobe_full_short_policy.get("run_id")
        or run_id != nested.public_bindings.get("run_id")
    ):
        raise OneRoundCampaignError("FULL_SHORT_RUN_ID_AUTHORITY_DRIFT")
    _collision_receipt, collision_sha256 = (
        _require_bound_run_collision_absence_v1(
            materialized, repo=repo, data_dir=data_dir,
            store_root=store_root, run_id=run_id, journal=journal,
        )
    )
    # Reserve every non-time worst-case counter before the sole real call.  A
    # crash after this point therefore cannot leave apparently reusable
    # provider/input/output capacity.  Elapsed time remains actual and is
    # advanced at the terminal transition.
    reserved_usage = dict(projected)
    reserved_usage["elapsed_seconds"] = int(state["usage"]["elapsed_seconds"])
    _validate_usage(reserved_usage, authorization=materialized.authorization)
    reserved_state = journal.append(
        "FULL_SHORT_RESERVED_NO_RESTART", usage=reserved_usage, evidence={
            "nested_authorization_sha256": nested.authorization_sha256,
            "full_short_run_collision_absence_receipt_sha256": (
                collision_sha256
            ),
            "replacement_run_allowed": False,
            "whole_run_retry_allowed": False,
        },
    )
    args = argparse.Namespace(
        repo=repo, data_dir=data_dir, store_root=store_root,
        authorization_raw=nested.authorization_raw,
        activated_sha256=nested.authorization_sha256,
        verified_external_workload_evidence=verified_evidence,
        external_workload_authorized_cases=capacity_authorized_cases(materialized.authorization),
        external_workload_authorization_sha256=materialized.authorization_sha256,
        external_workload_verification_keys={verification_key_id: verification_key},
    )
    started = time.monotonic()
    outer_usage_guard = build_full_short_outer_campaign_usage_guard_v1(
        campaign_authorization_sha256=materialized.authorization_sha256,
        prior_provider_request_count=int(state["usage"]["provider_requests"]),
        prior_input_tokens=int(state["usage"]["input_tokens"]),
        prior_output_tokens=int(state["usage"]["generated_output_tokens"]),
        remaining_provider_requests=(
            materialized.authorization["budgets"].get("plan_derived_max_provider_requests", MAX_PROVIDER_REQUESTS)
            - int(state["usage"]["provider_requests"])
        ),
        remaining_input_tokens=(
            materialized.authorization["budgets"]["plan_derived_max_input_tokens"] - int(state["usage"]["input_tokens"])
        ),
        remaining_output_tokens=(
            MAX_GENERATED_OUTPUT_TOKENS
            - int(state["usage"]["generated_output_tokens"])
        ),
        remaining_elapsed_seconds=(
            MAX_ELAPSED_SECONDS
            - int(reserved_state["usage"]["elapsed_seconds"])
        ),
        absolute_deadline_unix_seconds=(
            int(reserved_state["campaign_started_unix_seconds"])
            + MAX_ELAPSED_SECONDS
        ),
    )
    # This check is immediately before the production control plane can inspect
    # credentials or create its durable Full Short nonce.
    _require_campaign_time(reserved_state)
    _require_bound_run_collision_absence_v1(
        materialized, repo=repo, data_dir=data_dir,
        store_root=store_root, run_id=run_id, journal=journal,
    )
    try:
        nested_authorization = validate_full_short_canonical_authorization_v1(
            nested.authorization_raw,
            policy=nested.policy,
            public_bindings=nested.public_bindings,
        )
        result = await executor(
            args, nested_authorization,
            external_actions_enabled=True,
            secret_store_factory=KeyringSecretStore,
            outer_campaign_usage_guard=outer_usage_guard,
        )
        elapsed = math.ceil(time.monotonic() - started)
        terminal_usage = dict(reserved_state["usage"])
        terminal_usage["elapsed_seconds"] += elapsed
        _validate_usage(terminal_usage, authorization=materialized.authorization)
        completion = result.get("completion") if isinstance(result, Mapping) else None
        if not isinstance(completion, Mapping):
            raise OneRoundCampaignError("FULL_SHORT_COMPLETION_RECEIPT_MISSING")
        verified_actual_usage = result.get("verified_actual_usage")
        required_actual = {
            "full_short_provider_request_count",
            "full_short_input_tokens", "full_short_output_tokens",
            "campaign_cumulative_provider_request_count",
            "campaign_cumulative_input_tokens",
            "campaign_cumulative_output_tokens",
            "provider_reported_actual_complete",
        }
        if (
            not isinstance(verified_actual_usage, Mapping)
            or not required_actual.issubset(verified_actual_usage)
            or any(
                type(verified_actual_usage[field]) is not int
                or verified_actual_usage[field] < 0
                for field in required_actual
                if field != "provider_reported_actual_complete"
            )
            or type(verified_actual_usage[
                "provider_reported_actual_complete"
            ]) is not bool
            or verified_actual_usage["campaign_cumulative_provider_request_count"]
            > reserved_usage["provider_requests"]
            or verified_actual_usage["campaign_cumulative_input_tokens"]
            > reserved_usage["input_tokens"]
            or verified_actual_usage["campaign_cumulative_output_tokens"]
            > reserved_usage["generated_output_tokens"]
        ):
            raise OneRoundCampaignError("FULL_SHORT_ACTUAL_USAGE_RECEIPT_INVALID")
        verified_actual_usage = dict(verified_actual_usage)
        terminal_receipt = canonical_json_bytes({
            "completion_sha256": _json_sha256(completion),
            "terminal_sha256": _json_sha256(result.get("terminal")),
            "ledger_sha256": _json_sha256(result.get("ledger")),
            "verified_actual_usage_sha256": _json_sha256(
                verified_actual_usage
            ),
            "outer_campaign_usage_guard_sha256": outer_usage_guard[
                "guard_sha256"
            ],
            "raw_story_content_persisted": False,
        })
        _exclusive_write(
            materialized.evidence_root / "real-full-short-terminal-v1.json",
            terminal_receipt,
        )
        journal.append(
            "TERMINAL_FULL_SHORT_SUCCESS", usage=terminal_usage, evidence={
                "completion_receipt_sha256": _json_sha256(completion),
                "verified_actual_usage_sha256": _json_sha256(
                    verified_actual_usage
                ),
                "verified_actual_usage": verified_actual_usage,
                "conservative_liability_usage": reserved_usage,
                "real_full_short_terminal": "SUCCESS",
            },
        )
        return dict(result)
    except Exception as exc:
        failure_receipt = {
            "schema": "FullShortOneRoundTerminalFailureReceiptV1",
            "authorization_sha256": materialized.authorization_sha256,
            "nested_authorization_sha256": nested.authorization_sha256,
            "failure_type": type(exc).__name__,
            "failure_type_sha256": hashlib.sha256(
                type(exc).__name__.encode("utf-8")
            ).hexdigest(),
            "reserved_state_sha256": reserved_state["state_sha256"],
            "raw_exception_persisted": False,
        }
        _exclusive_write(
            materialized.evidence_root / "real-full-short-failure-v1.json",
            canonical_json_bytes(failure_receipt),
        )
        journal.append(
            "TERMINAL_FULL_SHORT_FAILURE", usage=reserved_usage, evidence={
                "failure_receipt_sha256": _json_sha256(failure_receipt),
                "failure_type": failure_receipt["failure_type"],
                "failure_type_sha256": failure_receipt["failure_type_sha256"],
                "raw_exception_persisted": False,
            },
        )
        raise


def _add_bundle_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--evidence-root", required=True, type=Path)
    parser.add_argument("--verification-key-id", required=True)
    parser.add_argument("--verification-key-file", required=True, type=Path)


def _print_phase_result(
    materialized: MaterializedCampaignV1, *, phase: str,
) -> None:
    print(json.dumps({
        "schema": "FullShortOneRoundPhaseResultV1",
        "authorization_sha256": materialized.authorization_sha256,
        "phase": phase,
        "final_execution_head": materialized.authorization[
            "frozen_execution"
        ]["final_execution_head"],
    }, sort_keys=True, separators=(",", ":")))


def finalize_size_matrix_evidence_v1(
    *, repo: Path, manifest_path: Path, junit_xml_path: Path,
    final_execution_head: str,
) -> dict[str, Any]:
    """Bind the completed pytest JUnit bytes to its raw envelope manifest."""

    repo = repo.resolve(strict=True)
    manifest_path = _require_outside_repo(
        repo, manifest_path, "SIZE_MATRIX_MANIFEST_INSIDE_GIT",
    )
    junit_xml_path = _require_outside_repo(
        repo, junit_xml_path, "SIZE_MATRIX_JUNIT_INSIDE_GIT",
    )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        junit_raw = junit_xml_path.read_bytes()
        junit_root = ElementTree.fromstring(junit_raw)
    except (OSError, UnicodeError, ValueError, ElementTree.ParseError):
        raise OneRoundCampaignError("SIZE_MATRIX_FINALIZATION_INPUT_INVALID") from None
    names = [
        str(item.attrib.get("name") or "")
        for item in junit_root.iter("testcase")
        if "test_full_short_real_http_seam" in str(item.attrib.get("name") or "")
        and not list(item)
    ]
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema") != "FullShortHttpSeamEnvelopeManifestV1"
        or manifest.get("source_head") != final_execution_head
        or manifest.get("test_file_sha256")
        != _repository_file_sha256_v1(repo, "tests/test_workflows.py")
        or [item.get("target_words") for item in manifest.get("run_records", [])]
        != [13_000, 20_000, 30_000]
        or not all(any(f"[{size}]" in name for name in names)
                   for size in (13_000, 20_000, 30_000))
    ):
        raise OneRoundCampaignError("SIZE_MATRIX_FINALIZATION_INPUT_INVALID")
    manifest["junit_xml_sha256"] = hashlib.sha256(junit_raw).hexdigest()
    raw = canonical_json_bytes(manifest)
    temporary = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    temporary.write_bytes(raw)
    os.replace(temporary, manifest_path)
    return {
        "schema": "FullShortSizeMatrixFinalizationReceiptV1",
        "manifest_path": str(manifest_path),
        "manifest_sha256": hashlib.sha256(raw).hexdigest(),
        "junit_xml_path": str(junit_xml_path),
        "junit_xml_sha256": manifest["junit_xml_sha256"],
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Run one explicit, journal-gated phase from canonical external state."""

    parser = argparse.ArgumentParser(
        description="Frozen-head one-round Full Short campaign controller.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    finalize_size_parser = subparsers.add_parser(
        "finalize-size-matrix",
        help="bind completed JUnit XML to the raw provider-envelope manifest",
    )
    finalize_size_parser.add_argument("--repo", required=True, type=Path)
    finalize_size_parser.add_argument("--manifest", required=True, type=Path)
    finalize_size_parser.add_argument("--junit-xml", required=True, type=Path)
    finalize_size_parser.add_argument("--final-execution-head", required=True)

    prepare_parser = subparsers.add_parser(
        "prepare", help="credential-free outer materialization",
    )
    _add_bundle_arguments(prepare_parser)
    prepare_parser.add_argument("--data-dir", required=True, type=Path)
    prepare_parser.add_argument("--store-root", required=True, type=Path)
    prepare_parser.add_argument("--logical-stage-plan", required=True, type=Path)
    prepare_parser.add_argument("--run-id", required=True)
    prepare_parser.add_argument("--expected-final-head", required=True)
    prepare_parser.add_argument("--shared-protocol-usage-recovery", action="store_true")
    prepare_parser.add_argument("--post-message-stop-ping-recovery", action="store_true")
    prepare_parser.add_argument("--anthropic-error-hardening", action="store_true")

    preflight_parser = subparsers.add_parser(
        "preflight", help="offline exact authorization/source revalidation",
    )
    _add_bundle_arguments(preflight_parser)
    preflight_parser.add_argument("--data-dir", required=True, type=Path)
    preflight_parser.add_argument("--store-root", required=True, type=Path)

    probe_parser = subparsers.add_parser(
        "probes", help="consume the single sequential eight-probe phase",
    )
    _add_bundle_arguments(probe_parser)
    probe_parser.add_argument("--data-dir", required=True, type=Path)
    probe_parser.add_argument("--store-root", required=True, type=Path)
    probe_parser.add_argument(
        "--confirm-authorized-paid-network", required=True,
        choices=["EXACT_8_SEQUENTIAL_PROBES_NO_RETRY", "EXACT_SELECTED_SUCCESSOR_PROBES_NO_RETRY"],
    )

    derive_parser = subparsers.add_parser(
        "derive-postprobe", help="derive and seal the evidence-bound nested auth",
    )
    _add_bundle_arguments(derive_parser)
    derive_parser.add_argument("--data-dir", required=True, type=Path)
    derive_parser.add_argument("--store-root", required=True, type=Path)

    gates_parser = subparsers.add_parser(
        "record-gates", help="validate source artifacts and derive gate receipts",
    )
    _add_bundle_arguments(gates_parser)
    gates_parser.add_argument(
        "--gate-source-evidence", required=True, action="append", type=Path,
        help="eight ordered canonical JSON artifacts: dry, size, strict, five reviews",
    )

    execute_parser = subparsers.add_parser(
        "execute-one", help="consume the sole real Full Short authorization",
    )
    _add_bundle_arguments(execute_parser)
    execute_parser.add_argument("--data-dir", required=True, type=Path)
    execute_parser.add_argument("--store-root", required=True, type=Path)
    execute_parser.add_argument(
        "--confirm-authorized-paid-network", required=True,
        choices=["EXECUTE_EXACTLY_ONE_REAL_FULL_SHORT_NO_RETRY"],
    )

    status_parser = subparsers.add_parser(
        "status", help="authenticate and print the latest external phase",
    )
    _add_bundle_arguments(status_parser)
    args = parser.parse_args(argv)
    if args.command == "finalize-size-matrix":
        receipt = finalize_size_matrix_evidence_v1(
            repo=args.repo, manifest_path=args.manifest,
            junit_xml_path=args.junit_xml,
            final_execution_head=args.final_execution_head,
        )
        print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
        return 0
    try:
        verification_key_path = _require_outside_repo(
            args.repo, args.verification_key_file,
            "CAMPAIGN_VERIFICATION_KEY_INSIDE_GIT",
        )
        verification_key = verification_key_path.read_bytes()
    except OSError:
        raise OneRoundCampaignError("CAMPAIGN_VERIFICATION_KEY_UNAVAILABLE") from None

    if args.command == "prepare":
        try:
            plan_document = json.loads(
                args.logical_stage_plan.read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, ValueError):
            raise OneRoundCampaignError(
                "FULL_SHORT_LOGICAL_STAGE_PLAN_INVALID"
            ) from None
        plan = (
            plan_document.get("logical_stage_plan")
            if isinstance(plan_document, dict) else plan_document
        )
        if not isinstance(plan, list):
            raise OneRoundCampaignError("FULL_SHORT_LOGICAL_STAGE_PLAN_INVALID")
        materialized = prepare_campaign_from_live_source_v1(
            repo=args.repo, data_dir=args.data_dir,
            evidence_root=args.evidence_root, store_root=args.store_root,
            logical_stage_plan=plan, run_id=args.run_id,
            verification_key_id=args.verification_key_id,
            verification_key=verification_key,
            expected_final_head=args.expected_final_head,
            shared_protocol_usage_recovery=args.shared_protocol_usage_recovery,
            post_message_stop_ping_recovery=args.post_message_stop_ping_recovery,
            anthropic_error_hardening=args.anthropic_error_hardening,
        )
        _print_phase_result(materialized, phase="MATERIALIZED_UNUSED")
        return 0

    materialized = load_materialized_campaign_v1(
        repo=args.repo, evidence_root=args.evidence_root,
        verification_key_id=args.verification_key_id,
        verification_key=verification_key,
    )
    if args.command == "probes":
        wanted = ("EXACT_SELECTED_SUCCESSOR_PROBES_NO_RETRY" if materialized.authorization.get("schema") in SUCCESSOR_SCHEMAS
            else "EXACT_8_SEQUENTIAL_PROBES_NO_RETRY")
        if args.confirm_authorized_paid_network != wanted:
            raise OneRoundCampaignError("PROBE_DISPATCH_SELECTION_CONFIRMATION_DRIFT")
    if args.command == "status":
        state = CampaignJournalV1(
            materialized.evidence_root, materialized.authorization_sha256,
            verification_key,
        ).load()
        _print_phase_result(materialized, phase=state["phase"])
        return 0

    if args.command in {"preflight", "probes"}:
        db = Database(args.data_dir.resolve(strict=True) / "app.db")
        fixtures = build_synthetic_probe_fixtures(
            ProviderRegistry(db, MemorySecretStore())
        )
        if args.command == "preflight":
            state = preflight_campaign_v1(
                materialized, repo=args.repo, data_dir=args.data_dir,
                store_root=args.store_root, fixtures=fixtures,
                full_short_policy=materialized.preprobe_full_short_policy,
                full_short_public_bindings=(
                    materialized.preprobe_full_short_public_bindings
                ),
                verification_key_id=args.verification_key_id,
                verification_key=verification_key,
            )
            _print_phase_result(materialized, phase=state["phase"])
            return 0
        run_probe_phase_v1(
            materialized, repo=args.repo, fixtures=fixtures, db=db,
            store_root=args.store_root,
            verification_key_id=args.verification_key_id,
            verification_key=verification_key,
        )
        _print_phase_result(materialized, phase="PROBE_ALL_PASS")
        return 0

    verified = load_verified_probe_evidence_v1(
        materialized, verification_key_id=args.verification_key_id,
        verification_key=verification_key,
    )
    if args.command == "derive-postprobe":
        derive_post_probe_authorization_v1(
            materialized, repo=args.repo, data_dir=args.data_dir,
            store_root=args.store_root,
            template_policy=materialized.preprobe_full_short_policy,
            verified_evidence=verified,
            verification_key_id=args.verification_key_id,
            verification_key=verification_key,
        )
        _print_phase_result(
            materialized, phase="POST_PROBE_AUTHORIZATION_SEALED",
        )
        return 0

    nested = load_post_probe_authorization_v1(materialized)
    if args.command == "record-gates":
        if len(args.gate_source_evidence) != 8:
            raise OneRoundCampaignError("MANDATORY_GATE_EVIDENCE_COUNT_INVALID")
        state = record_mandatory_gates_v1(
            materialized, nested, repo=args.repo,
            verified_evidence=verified,
            verification_key_id=args.verification_key_id,
            verification_key=verification_key,
            gate_evidence_paths=tuple(args.gate_source_evidence),
        )
        _print_phase_result(materialized, phase=state["phase"])
        return 0

    if args.command == "execute-one":
        asyncio.run(execute_one_full_short_v1(
            materialized, nested, repo=args.repo, data_dir=args.data_dir,
            store_root=args.store_root, verified_evidence=verified,
            verification_key_id=args.verification_key_id,
            verification_key=verification_key,
        ))
        _print_phase_result(materialized, phase="TERMINAL_FULL_SHORT_SUCCESS")
        return 0
    raise OneRoundCampaignError("CAMPAIGN_COMMAND_INVALID")


__all__ = [
    "CampaignJournalV1",
    "MandatoryGateReceiptsV1",
    "MaterializedCampaignV1",
    "OneRoundCampaignError",
    "PostProbeAuthorizationV1",
    "build_outer_authorization_v1",
    "derive_post_probe_authorization_v1",
    "execute_one_full_short_v1",
    "finalize_size_matrix_evidence_v1",
    "load_materialized_campaign_v1",
    "load_post_probe_authorization_v1",
    "load_verified_probe_evidence_v1",
    "materialize_campaign_authorization_v1",
    "preflight_campaign_v1",
    "prepare_campaign_from_live_source_v1",
    "record_mandatory_gates_v1",
    "run_probe_phase_v1",
]


if __name__ == "__main__":
    raise SystemExit(main())
