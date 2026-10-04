"""A bounded, provider-agnostic generated-root recovery operation.

The operation owns only the durable recovery boundary.  A caller supplies the
already reconstructed :class:`DraftTaskContract` and a semantic validator;
this module binds their result to the candidate, event scope, dispatch claim,
and next checkpoint without reconstructing prose or choosing a provider.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping

from novel_flywheel.db import Database
from novel_flywheel.draft_split import DraftTaskContract
from novel_flywheel.generated_root_authority import (
    AuthorityReconciliation,
    reconcile_generated_root_authority,
)


CandidateLoader = Callable[[str], tuple[str, str, str]]
SemanticValidator = Callable[
    [DraftTaskContract, str],
    Awaitable["GeneratedRootSemanticValidation"] | "GeneratedRootSemanticValidation",
]


@dataclass(frozen=True)
class GeneratedRootSemanticValidation:
    """A semantic receipt already checked by the caller's native validator."""

    receipt: Mapping[str, Any]
    provider_call_executed: bool


@dataclass(frozen=True)
class GeneratedRootRecoveryRequest:
    run_id: str
    project_id: str
    task_id: str
    candidate_relative_path: str
    candidate_prose_sha256: str
    candidate_raw_sha256: str
    authority: Mapping[str, Any]
    contract: DraftTaskContract
    route_identity_sha256: str
    request_condition_sha256: str
    node_key: str
    max_dispatches: int = 1
    max_dispatches_per_route: int = 1
    next_node: str = "review"


@dataclass(frozen=True)
class GeneratedRootRecoveryResult:
    run_id: str
    attempt: int
    checkpoint: Mapping[str, Any]
    provider_call_executed: bool
    released_attempts: tuple[int, ...]
    reconciliation: AuthorityReconciliation

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "attempt": self.attempt,
            "checkpoint": dict(self.checkpoint),
            "provider_call_executed": self.provider_call_executed,
            "released_attempts": list(self.released_attempts),
            "reconciliation": self.reconciliation.to_dict(),
        }


class GeneratedRootRecoveryValidationError(RuntimeError):
    """A bounded validation failure with an explicit transport disposition."""

    def __init__(self, message: str, *, provider_call_executed: bool | None = False):
        super().__init__(message)
        self.provider_call_executed = provider_call_executed


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def _maybe_await(value: Any) -> Any:
    if hasattr(value, "__await__"):
        return await value
    return value


class GeneratedRootRecoveryOperation:
    """Execute one exact generated-root recovery attempt.

    The operation is callable in ``RunTaskManager``'s ``RunOperation`` shape.
    It never creates a new run and never retries a provider request itself.
    """

    def __init__(
        self,
        db: Database,
        request: GeneratedRootRecoveryRequest,
        *,
        candidate_loader: CandidateLoader,
        semantic_validator: SemanticValidator,
    ) -> None:
        self.db = db
        self.request = request
        self.candidate_loader = candidate_loader
        self.semantic_validator = semantic_validator

    async def __call__(self, run_id: str) -> dict[str, Any]:
        result = await self.execute(run_id)
        return result.to_dict()

    async def execute(self, run_id: str) -> GeneratedRootRecoveryResult:
        request = self.request
        if run_id != request.run_id:
            raise ValueError("generated-root recovery run identity mismatch")
        run = self.db.get_run(run_id)
        if (
            run is None
            or str(run.get("project_id")) != request.project_id
            or str(run.get("workflow")) != "short-story"
            or str(run.get("status")) not in {
                "failed", "cancelled", "waiting_provider", "interrupted", "running",
            }
        ):
            raise ValueError("generated-root recovery run is not resumable")

        if request.contract.task_id != request.task_id:
            raise ValueError("generated-root contract task identity mismatch")
        if request.contract.authority_sha256 != str(
            request.authority.get("contract_authority_sha256") or ""
        ):
            raise ValueError("generated-root contract authority mismatch")
        if request.contract.execution_manifest_sha256 != str(
            request.authority.get("execution_manifest_sha256") or ""
        ):
            raise ValueError("generated-root contract manifest mismatch")
        if (
            request.route_identity_sha256 != str(
                request.authority.get("route_identity_sha256") or ""
            )
            or request.request_condition_sha256 != str(
                request.authority.get("request_condition_sha256") or ""
            )
        ):
            raise ValueError("generated-root dispatch identity mismatch")

        prose, raw_sha256, prose_sha256 = self.candidate_loader(
            request.candidate_relative_path,
        )
        if raw_sha256 != request.candidate_raw_sha256:
            raise ValueError("generated-root candidate raw hash mismatch")
        if prose_sha256 != request.candidate_prose_sha256:
            raise ValueError("generated-root candidate prose hash mismatch")
        if _sha256_text(prose) != request.candidate_prose_sha256:
            raise ValueError("generated-root candidate content hash mismatch")
        checkpoint_input_sha256 = str(
            request.authority.get("checkpoint_input_sha256") or ""
        )
        if len(checkpoint_input_sha256) != 64:
            raise ValueError("generated-root checkpoint input identity is missing")

        checkpoints = self.db.list_workflow_node_checkpoints(
            run_id=run_id,
            node_key=request.node_key,
            authority_sha256=str(request.authority.get("authority_sha256") or ""),
            statuses=("generated_complete", "validated", "transport", "failed", "stale"),
            output_sha256=request.candidate_prose_sha256,
        )
        reconciliation = reconcile_generated_root_authority(
            request.authority,
            filesystem_candidate_prose_sha256=prose_sha256,
            events=self.db.list_run_events(run_id),
            checkpoints=checkpoints,
            require_event_pair=True,
            require_dispatch_identity=True,
            require_checkpoint=False,
        )
        if not reconciliation.ok:
            # A new validated checkpoint is allowed; an existing ambiguous or
            # conflicting checkpoint is not.  The reconciliation object keeps
            # the failure reason durable for the caller without guessing.
            if checkpoints or reconciliation.matching_checkpoint_count:
                raise ValueError(
                    "generated-root authority reconciliation failed: "
                    + ",".join(reconciliation.issues)
                )
            checkpoint_issues = tuple(
                issue for issue in reconciliation.issues
                if issue != "missing_candidate_checkpoint"
            )
            if checkpoint_issues:
                raise ValueError(
                    "generated-root authority reconciliation failed: "
                    + ",".join(checkpoint_issues)
                )

        authority_sha256 = str(request.authority.get("authority_sha256") or "")
        attempt = self.db.claim_review_requalification_dispatch(
            run_id=run_id,
            authorization_sha256=authority_sha256,
            route_identity_sha256=request.route_identity_sha256,
            request_condition_sha256=request.request_condition_sha256,
            max_dispatches=request.max_dispatches,
            max_dispatches_per_route=request.max_dispatches_per_route,
        )
        provider_call_executed: bool | None = None
        try:
            validation = await _maybe_await(
                self.semantic_validator(request.contract, prose),
            )
            if not isinstance(validation, GeneratedRootSemanticValidation):
                raise GeneratedRootRecoveryValidationError(
                    "semantic validator returned an invalid result",
                )
            provider_call_executed = validation.provider_call_executed
            output_sha256 = _sha256_text(prose)
            saved = self.db.save_workflow_node_checkpoint(
                run_id=run_id,
                node_key=request.node_key,
                authority_sha256=authority_sha256,
                input_sha256=checkpoint_input_sha256,
                output_sha256=output_sha256,
                status="validated",
                route_fingerprint=request.route_identity_sha256,
                next_node=request.next_node,
                validation_stage="promoted",
                payload={
                    "recovery_authority": dict(request.authority),
                    "task_id": request.task_id,
                    "candidate_relative_path": request.candidate_relative_path,
                    "semantic_receipt": dict(validation.receipt),
                },
            )
            released: list[int] = []
            if provider_call_executed:
                self.db.finalize_review_requalification_dispatch(
                    run_id=run_id, attempt=attempt,
                    authorization_sha256=authority_sha256, state="qualified",
                )
            else:
                released = self.db.release_unexecuted_review_requalification_claims(
                    run_id=run_id, authorization_sha256=authority_sha256,
                    after_attempt=attempt - 1,
                )
            return GeneratedRootRecoveryResult(
                run_id=run_id, attempt=attempt, checkpoint=saved,
                provider_call_executed=bool(provider_call_executed),
                released_attempts=tuple(released),
                reconciliation=reconciliation,
            )
        except GeneratedRootRecoveryValidationError as exc:
            provider_call_executed = exc.provider_call_executed
            self.db.finalize_review_requalification_dispatch(
                run_id=run_id, attempt=attempt,
                authorization_sha256=authority_sha256, state="deterministic_failure",
                failure_class="generated_root_validation",
            )
            if provider_call_executed is False:
                self.db.release_unexecuted_review_requalification_claims(
                    run_id=run_id, authorization_sha256=authority_sha256,
                    after_attempt=attempt - 1,
                )
            raise
        except Exception:
            # Unknown transport disposition stays consumed.  Releasing an
            # attempt without an explicit false receipt would permit a duplicate.
            if provider_call_executed is False:
                self.db.release_unexecuted_review_requalification_claims(
                    run_id=run_id, authorization_sha256=authority_sha256,
                    after_attempt=attempt - 1,
                )
            raise
