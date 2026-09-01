from __future__ import annotations

"""Deterministic source audit for the Full Short stop-loss metrics."""

import argparse
import ast
import hashlib
import inspect
import json
from pathlib import Path
import re
import textwrap
from typing import Any

from novel_flywheel.execution_failure_architecture import (
    DURABLE_FAILURE_EVIDENCE_POLICY_SHA256,
    FAILURE_ARCHITECTURE_IDENTITY,
    FULL_SHORT_EXACT_RECOVERY_REGISTRY_SHA256,
    NONCE_RESERVATION_POLICY_SHA256,
    OBSERVER_ISOLATION_POLICY_SHA256,
    PREDISPATCH_STATE_MACHINE_SHA256,
    _ordered_children,
)
from novel_flywheel.full_short_execution import (
    FullShortDispatchLedgerObserverV1,
    FullShortDurableExecutionStoreV1,
    FullShortExecutionBoundaryError,
    _validate_ledger_mutation_v1,
)
from novel_flywheel.full_short_reason_catalog import (
    FULL_SHORT_LITERAL_REASON_CATEGORY_V1,
)
from novel_flywheel.models import ModelGateway, ModelRoutesExhaustedError
from novel_flywheel.providers.http import HttpProvider
from novel_flywheel.tasks import RunTaskManager
from novel_flywheel.workflows import WorkflowService
from tools.canary.first_trustworthy_full_short_runner import (
    _execute_full_short_control_plane_with_capability,
    execute_full_short_control_plane,
)


_METRIC_CHECKS: dict[str, tuple[str, ...]] = {
    "locally_predictable_unmapped_failure_count": (
        "full_short_reason_catalog_is_ast_closed",
        "phase9_inventory_is_source_bound",
        "phase9_campaign_uses_real_boundaries",
        "phase9_campaign_requires_junit_receipts",
    ),
    "generic_wrapper_without_child_provenance_count": (
        "terminal_failure_uses_durable_graph",
        "route_exhaustion_preserves_ordered_children",
    ),
    "failure_without_durable_receipt_count": (
        "terminal_failure_uses_durable_graph",
        "phase9_campaign_requires_junit_receipts",
    ),
    "recoverable_failure_without_bounded_policy_count": (
        "production_dispatch_queries_recovery_registry",
        "gateway_exact_mode_precedes_retry_and_fallback",
        "workflow_exact_plan_has_no_fallback",
    ),
    "restart_ambiguity_count": (
        "post_nonce_crash_is_nonrestartable",
        "durable_ledger_rejects_unregistered_transitions",
    ),
    "nonce_premature_reservation_path_count": (
        "runner_has_no_premature_reserve_nonce",
        "dispatch_ready_precedes_nonce",
        "wire_request_build_precedes_nonce",
    ),
    "observer_business_coupling_count": (
        "control_stage_receipt_precedes_diagnostics",
    ),
    "hidden_retry_path_count": (
        "gateway_exact_mode_precedes_retry_and_fallback",
        "workflow_exact_plan_has_no_fallback",
    ),
    "authority_mutation_before_accepted_receipt_count": (
        "control_stage_receipt_precedes_diagnostics",
        "durable_ledger_rejects_unregistered_transitions",
    ),
}


def _sha(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _source(value: Any) -> str:
    result = textwrap.dedent(inspect.getsource(value))
    ast.parse(result)
    return result


def audit() -> dict[str, Any]:
    public_runner = _source(execute_full_short_control_plane)
    runner = _source(_execute_full_short_control_plane_with_capability)
    full_short_source_paths = (
        Path(inspect.getfile(FullShortExecutionBoundaryError)),
        Path(inspect.getfile(
            __import__(
                "tools.canary.first_trustworthy_full_short_runner",
                fromlist=["execute_full_short_control_plane"],
            ).execute_full_short_control_plane
        )),
    )
    literal_reasons: set[str] = set()
    nodes = (
        node
        for source_path in full_short_source_paths
        for node in ast.walk(ast.parse(
            source_path.read_text(encoding="utf-8")
        ))
    )
    for node in nodes:
        if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
            for argument in node.exc.args[:1]:
                for child in ast.walk(argument):
                    if not (
                        isinstance(child, ast.Constant)
                        and isinstance(child.value, str)
                    ):
                        continue
                    match = re.match(
                        r"^([A-Z][A-Z0-9_]+)(?::|$)", child.value,
                    )
                    if match:
                        literal_reasons.add(match.group(1))
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if (
                keyword.arg == "reason"
                and isinstance(keyword.value, ast.Constant)
                and isinstance(keyword.value.value, str)
            ):
                literal_reasons.add(keyword.value.value)
        if not isinstance(node.func, ast.Name):
            continue
        argument = None
        if node.func.id == "_require" and len(node.args) > 1:
            argument = node.args[1]
        elif node.func.id == "FullShortExecutionBoundaryError" and node.args:
            argument = node.args[0]
        if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
            literal_reasons.add(argument.value)
    literal_reasons.update({
        "APPROVAL_NOT_FOUND_OR_CORRUPT",
        "LEDGER_NOT_FOUND_OR_CORRUPT",
        "NONCE_NOT_FOUND_OR_CORRUPT",
        "PERMISSION_NOT_FOUND_OR_CORRUPT",
    })
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
    campaign_path = Path("tests/test_full_short_failure_surface_campaign.py")
    campaign = campaign_path.read_text(encoding="utf-8")
    campaign_ast = ast.parse(campaign)
    campaign_functions = {
        node.name for node in ast.walk(campaign_ast)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    checks = {
        "full_short_reason_catalog_is_ast_closed": (
            literal_reasons == set(FULL_SHORT_LITERAL_REASON_CATEGORY_V1)
            and all(
                not FullShortExecutionBoundaryError(
                    code
                ).reliability_failure.code.startswith("unmapped_")
                for code in literal_reasons
            )
        ),
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
            in public_runner
            and "_LowestHttpSeamRegistry" in _source(
                __import__(
                    "tools.canary.first_trustworthy_full_short_runner",
                    fromlist=["_execute_full_short_control_plane_offline"],
                )._execute_full_short_control_plane_offline
            )
            and "OFFLINE_REGISTRY_TRANSPORT_BINDING_NOT_EXACT" in _source(
                __import__(
                    "tools.canary.first_trustworthy_full_short_runner",
                    fromlist=["_registry_from_factory"],
                )._registry_from_factory
            )
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
        "route_exhaustion_preserves_ordered_children": (
            "route_errors" in _source(ModelRoutesExhaustedError)
            and "enumerate(route_errors, 1)" in _source(_ordered_children)
            and "children.append((candidate, ordinal" in _source(_ordered_children)
        ),
        "phase9_inventory_is_source_bound": (
            "PHASE9_FAULT_CASES" in campaign
            and "behavioral_test" in campaign
            and "detection_point" in campaign
            and "test_phase9_campaign_catalog_is_source_bound" in campaign_functions
        ),
        "phase9_campaign_uses_real_boundaries": (
            "ExecutionBoundaryFailure(" not in campaign
            and "build_durable_failure_evidence(" not in campaign
            and "behavioral_test" in campaign
        ),
        "phase9_campaign_requires_junit_receipts": (
            "fault_campaign_junit" in campaign
            and "source_head" in campaign
            and "testcase" in campaign
        ),
    }
    failures = sorted(key for key, passed in checks.items() if not passed)
    metrics = {
        metric: sum(not checks.get(check, False) for check in required_checks)
        for metric, required_checks in _METRIC_CHECKS.items()
    }
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
            "public_runner": _sha(public_runner),
            "runner": _sha(runner), "dispatch": _sha(dispatch),
            "nonce_boundary": _sha(registry_boundary),
            "ledger_transition": _sha(ledger_transition),
            "http_stream": _sha(http_stream),
            "gateway_complete": _sha(gateway_complete),
            "gateway_tools": _sha(gateway_tools), "stage": _sha(stage),
            "protocol_plan": _sha(protocol_plan),
            "failure_record": _sha(failure_record),
            "full_short_reason_catalog": _sha(json.dumps(
                FULL_SHORT_LITERAL_REASON_CATEGORY_V1,
                sort_keys=True, separators=(",", ":"),
            )),
            "phase9_campaign": _sha(campaign),
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
