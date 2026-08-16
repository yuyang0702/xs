"""Hash-bound, read-only Short completion definitions."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from novel_flywheel.runtime_fingerprint_build import (
    CANONICALIZATION_VERSION,
    domain_sha256,
)

from .approval_profiles import SHORT_COMPLETION_PROFILE_ID, approval_profile
from .artifact_hash import file_sha256


COMPLETION_GOAL = "SHORT_WORKFLOW_COMPLETED_AND_FINAL_REVIEW_ACCEPTED"
FINAL_REVIEW_CONTRACT_ID = "short_formal_quality_authority"
FINAL_REVIEW_CONTRACT_VERSION = 1
QUALITY_CHECKPOINT_VERSION = 1


def _definition(schema: str, payload: dict[str, Any]) -> dict[str, Any]:
    body = {
        "schema": schema,
        "version": 1,
        "canonicalization_version": CANONICALIZATION_VERSION,
        **deepcopy(payload),
    }
    return {
        **body,
        "definition_sha256": domain_sha256(
            f"novel-flywheel-short-completion:{schema}", body,
        ),
    }


def _production_source_hash(relative: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return file_sha256(root / relative)


def completion_contract_bundle_v1() -> dict[str, dict[str, Any]]:
    """Build definitions from the current production bytes without mutation."""

    profile = approval_profile(SHORT_COMPLETION_PROFILE_ID)
    workflows_hash = _production_source_hash("src/novel_flywheel/workflows.py")
    quality_hash = _production_source_hash("src/novel_flywheel/quality_records.py")
    prose_hash = _production_source_hash("src/novel_flywheel/prose_quality.py")
    journal_hash = _production_source_hash(
        "src/novel_flywheel/project_transactions.py"
    )
    stop_conditions = _definition("ShortCompletionStopConditionManifestV1", {
        "profile_id": profile.profile_id,
        "ordered_conditions": list(profile.stop_condition_policy),
        "first_terminal_stop": True,
        "resume_after_terminal": False,
        "second_run_allowed": False,
    })
    draft_validator = _definition("DraftValidatorPolicyV1", {
        "production_source_sha256": prose_hash,
        "integrity_receipt": "outputs/draft-integrity.json",
        "accepted_status": "passed",
        "publication_hash_fields": ["publication_sha256", "draft_sha256"],
        "fail_closed": True,
    })
    mixed_script = _definition("AuthorityAwareMixedScriptPolicyV1", {
        "production_source_sha256": prose_hash,
        "normalization_version": "nfkc-case-sensitive-exact-token-v1",
        "authority_required_for_exception": True,
        "unknown_or_stale_authority_rejected": True,
        "r1_d1_declared_validator_policy_sha256": (
            "7e9875e3341f811fc3882b8161de6ca9f4e81243ce0262a0b1c72cb54353c940"
        ),
    })
    final_review = _definition("FinalReviewCompletionDefinitionV1", {
        "production_workflows_sha256": workflows_hash,
        "production_quality_records_sha256": quality_hash,
        "contract_id": FINAL_REVIEW_CONTRACT_ID,
        "contract_version": FINAL_REVIEW_CONTRACT_VERSION,
        "receipt_schema": "quality-report.json",
        "accepted_outcome_code": "passed",
        "rejected_outcome_codes": ["conditional_pass", "failed"],
        "terminal_review_complete_required": True,
        "binding_field": "terminal_reviewed_hash",
        "binding_algorithm": "sha256_utf8",
    })
    maintenance = _definition("ShortMaintenanceCompletionDefinitionV1", {
        "production_workflows_sha256": workflows_hash,
        "production_journal_sha256": journal_hash,
        "stage_identity": "maintenance",
        "formal_entry": "WorkflowEngine._close_short_maintenance_authority",
        "receipt_globs": [
            "receipts/maintenance-inventory-*.json",
            "receipts/maintenance-reduction-*.json",
        ],
        "conversion_validation_required": True,
        "transaction_closure": "ProjectMutationJournalV1.status=committed",
        "phase1b_candidate_required": False,
        "hold_or_failure_is_not_completion": True,
    })
    final_artifact = _definition("FinalArtifactBindingPolicyV1", {
        "production_workflows_sha256": workflows_hash,
        "artifact_kind": "formal_short_manuscript",
        "relative_path": "manuscript/story.md",
        "non_empty": True,
        "binding_algorithm": "sha256_utf8",
        "must_equal_final_review_hash": True,
    })
    final_checkpoint = _definition("FinalCheckpointClosurePolicyV1", {
        "production_quality_records_sha256": quality_hash,
        "relative_path": "outputs/quality-checkpoint.json",
        "checkpoint_version": QUALITY_CHECKPOINT_VERSION,
        "accepted_outcome": "passed",
        "required_hash_fields": ["manuscript_hash", "terminal_reviewed_hash"],
        "must_equal_final_manuscript": True,
    })
    completion_goal = _definition("CompletionGoalDefinitionV1", {
        "profile_id": profile.profile_id,
        "goal": COMPLETION_GOAL,
        "workflow_status": "completed",
        "required_definition_hashes": {
            "draft_validator_policy_sha256": draft_validator["definition_sha256"],
            "mixed_script_policy_sha256": mixed_script["definition_sha256"],
            "final_review_definition_sha256": final_review["definition_sha256"],
            "maintenance_definition_sha256": maintenance["definition_sha256"],
            "final_artifact_policy_sha256": final_artifact["definition_sha256"],
            "final_checkpoint_policy_sha256": final_checkpoint["definition_sha256"],
        },
        "phase1b_required": False,
        "live_isolation_required": True,
    })
    return {
        "stop_conditions": stop_conditions,
        "draft_validator_policy": draft_validator,
        "mixed_script_policy": mixed_script,
        "final_review": final_review,
        "maintenance": maintenance,
        "final_artifact": final_artifact,
        "final_checkpoint": final_checkpoint,
        "completion_goal": completion_goal,
    }
