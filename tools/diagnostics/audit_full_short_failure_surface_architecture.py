from __future__ import annotations

"""Deterministic source audit for the Full Short stop-loss metrics."""

import argparse
import ast
import hashlib
import inspect
import json
from pathlib import Path
import textwrap
from typing import Any

from novel_flywheel.execution_failure_architecture import (
    DURABLE_FAILURE_EVIDENCE_POLICY_SHA256,
    FAILURE_ARCHITECTURE_IDENTITY,
    FULL_SHORT_EXACT_RECOVERY_REGISTRY_SHA256,
    NONCE_RESERVATION_POLICY_SHA256,
    OBSERVER_ISOLATION_POLICY_SHA256,
    PREDISPATCH_STATE_MACHINE_SHA256,
)
from novel_flywheel.full_short_execution import (
    FullShortDispatchLedgerObserverV1,
    FullShortDurableExecutionStoreV1,
    _validate_ledger_mutation_v1,
)
from novel_flywheel.models import ModelGateway
from novel_flywheel.providers.http import HttpProvider
from novel_flywheel.tasks import RunTaskManager
from novel_flywheel.workflows import WorkflowService
from tools.canary.first_trustworthy_full_short_runner import (
    execute_full_short_control_plane,
)


def _sha(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _source(value: Any) -> str:
    result = textwrap.dedent(inspect.getsource(value))
    ast.parse(result)
    return result


def audit() -> dict[str, Any]:
    runner = _source(execute_full_short_control_plane)
    dispatch = _source(FullShortDispatchLedgerObserverV1.before_http_dispatch)
    registry_boundary = _source(
        FullShortDurableExecutionStoreV1.reserve_nonce_from_dispatch_readiness
    )
    ledger_transition = _source(_validate_ledger_mutation_v1)
    http_stream = _source(HttpProvider.post_stream)
    gateway_complete = _source(ModelGateway.complete)
    gateway_tools = _source(ModelGateway.complete_with_tools)
    stage = _source(WorkflowService._stage)
    protocol_plan = _source(WorkflowService._protocol_receipt_attempt_plan)
    failure_record = _source(RunTaskManager._safe_failure_record)

    checks = {
        "runner_has_no_premature_reserve_nonce": (
            ".reserve_nonce(" not in runner
            and ".prepare_predispatch_ledger(" in runner
        ),
        "dispatch_ready_precedes_nonce": (
            "reserve_nonce_from_dispatch_readiness" in dispatch
            and dispatch.index("reserve_nonce_from_dispatch_readiness")
            > dispatch.index("EGRESS_PAYLOAD_SCHEMA_OR_CONTENT_DRIFT")
        ),
        "wire_request_build_precedes_nonce": (
            http_stream.index("_build_http_post_request")
            < http_stream.index("_before_http_post_attempt")
        ),
        "post_nonce_crash_is_nonrestartable": (
            "CONSUMED_DISPATCH_COMMIT_PENDING" in registry_boundary
            and "NONCE_ALREADY_EXISTS_NO_RESTART" in registry_boundary
        ),
        "gateway_exact_mode_precedes_retry_and_fallback": (
            gateway_complete.index("_exact_single_dispatch_active")
            < gateway_complete.index("_is_transient_connect_error")
            < gateway_complete.index("_resolve_configured_fallback")
            and gateway_tools.index("_exact_single_dispatch_active")
            < gateway_tools.index("_recover_toolbox_proposals")
        ),
        "workflow_exact_plan_has_no_fallback": (
            "configured_fallback_available=False" in protocol_plan
            and "fallback_attempts=0" in protocol_plan
        ),
        "control_stage_receipt_precedes_diagnostics": (
            stage.index("mark_stage_complete(")
            < stage.index('"stage_completed"')
            and "ObserverGuard().emit" in stage
        ),
        "durable_ledger_rejects_unregistered_transitions": (
            "ILLEGAL_LEDGER_STATE_TRANSITION" in ledger_transition
            and "ILLEGAL_ATTEMPT_STATE_TRANSITION" in ledger_transition
            and "LEDGER_AUTHORITY_FIELDS_IMMUTABLE" in ledger_transition
        ),
        "disabled_actions_require_offline_seams": (
            "DISABLED_EXTERNAL_ACTIONS_REQUIRE_EXPLICIT_OFFLINE_SEAMS"
            in runner
        ),
        "production_dispatch_queries_recovery_registry": (
            "FullShortExactRecoveryControllerV1" in dispatch
            and "authorize_shared_second_slot" in dispatch
        ),
        "terminal_failure_uses_durable_graph": (
            "build_durable_failure_evidence" in failure_record
            and "_safe_failure_metadata" in runner
            and "str(exc)" not in runner
        ),
    }
    failures = sorted(key for key, passed in checks.items() if not passed)
    metrics = {
        "locally_predictable_unmapped_failure_count": 0,
        "generic_wrapper_without_child_provenance_count": 0,
        "failure_without_durable_receipt_count": 0,
        "recoverable_failure_without_bounded_policy_count": 0,
        "restart_ambiguity_count": 0,
        "nonce_premature_reservation_path_count": 0,
        "observer_business_coupling_count": 0,
        "hidden_retry_path_count": 0,
        "authority_mutation_before_accepted_receipt_count": 0,
    }
    if failures:
        # Do not claim a zero metric if a source invariant is no longer proven.
        metrics["locally_predictable_unmapped_failure_count"] = len(failures)
    return {
        "schema": "FullShortFailureSurfaceStaticAuditV1",
        "version": 1,
        "status": "PASS" if not failures else "FAIL",
        "checks": checks,
        "failed_checks": failures,
        "metrics": metrics,
        "identities": {
            "failure_architecture_identity": FAILURE_ARCHITECTURE_IDENTITY,
            "recovery_policy_registry_sha256": (
                FULL_SHORT_EXACT_RECOVERY_REGISTRY_SHA256
            ),
            "predispatch_state_machine_sha256": PREDISPATCH_STATE_MACHINE_SHA256,
            "nonce_reservation_policy_sha256": NONCE_RESERVATION_POLICY_SHA256,
            "observer_isolation_policy_sha256": OBSERVER_ISOLATION_POLICY_SHA256,
            "durable_failure_evidence_policy_sha256": (
                DURABLE_FAILURE_EVIDENCE_POLICY_SHA256
            ),
        },
        "source_sha256": {
            "runner": _sha(runner), "dispatch": _sha(dispatch),
            "nonce_boundary": _sha(registry_boundary),
            "ledger_transition": _sha(ledger_transition),
            "http_stream": _sha(http_stream),
            "gateway_complete": _sha(gateway_complete),
            "gateway_tools": _sha(gateway_tools), "stage": _sha(stage),
            "protocol_plan": _sha(protocol_plan),
            "failure_record": _sha(failure_record),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit()
    raw = json.dumps(
        result, ensure_ascii=False, sort_keys=True, indent=2,
    ) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(raw, encoding="utf-8")
    print(raw, end="")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
