from __future__ import annotations

import ast
from pathlib import Path

from tools.diagnostics.bind_full_short_runtime_source_exits import (
    _DYNAMIC_EDGE_CALLSITE_SHA256,
    _collect_functions,
    _direct_path_metric_violations_v1,
    _kernel_activation_evidence_v1,
    DIRECT_PATH_METRIC_NAMES_V1,
    FULL_SHORT_RUNTIME_PROOF_DOMAIN_V1,
    bind_exit_states_v1,
    build_source_exit_inventory_v1,
)


def test_source_exit_binding_closes_from_real_execution_roots() -> None:
    result = build_source_exit_inventory_v1(Path.cwd())

    assert FULL_SHORT_RUNTIME_PROOF_DOMAIN_V1["proof_domain_explicit"] is True
    assert result["status"] == "PASS", result["failure_summary"]
    assert result["source_failure_exit_count"] > 0
    assert result["unbound_source_failure_exit_count"] == 0
    assert result["unresolved_critical_edge_count"] == 0
    assert result["stale_dynamic_edge_contract_count"] == 0
    assert result["unreachable_registered_boundary_count"] == 0
    assert result["registry_entry_without_exact_wrapper_count"] == 0
    assert result["kernel_activation_root_without_evidence_count"] == 0
    assert result["direct_path_metrics"] == {
        name: 0 for name in DIRECT_PATH_METRIC_NAMES_V1
    }
    for name in DIRECT_PATH_METRIC_NAMES_V1:
        assert result[name] == 0


def test_binding_algorithm_detects_a_protected_path_bypass() -> None:
    result = bind_exit_states_v1(
        graph={
            "root": {"boundary", "helper"},
            "boundary": {"helper"},
            "helper": set(),
        },
        roots={"root": None},
        boundary_entries={"boundary": "FS.TEST"},
        exits_by_function={"helper": {"exit-1"}},
    )

    assert result["exit-1"]["protected_path_count"] == 1
    assert result["exit-1"]["unprotected_path_count"] == 1
    assert result["exit-1"]["disposition"] == "UNBOUND"


def test_kernel_activation_roots_require_structural_evidence() -> None:
    context_tree = ast.parse("""
async def root():
    with activate_full_short_kernel_v1(kernel):
        await operation()
""")
    direct_tree = ast.parse("""
def terminal():
    return runtime_kernel.execute_boundary_sync("FS.TEST", operation)
""")
    unsafe_tree = ast.parse("""
async def unsafe():
    await service.run_short("project")
""")
    context_root = context_tree.body[0]
    direct_root = direct_tree.body[0]
    unsafe_root = unsafe_tree.body[0]
    assert isinstance(context_root, ast.AsyncFunctionDef)
    assert isinstance(direct_root, ast.FunctionDef)
    assert isinstance(unsafe_root, ast.AsyncFunctionDef)
    assert _kernel_activation_evidence_v1(
        context_root, "context_activation",
    )
    assert _kernel_activation_evidence_v1(
        direct_root, "explicit_kernel_boundary",
    )
    assert not _kernel_activation_evidence_v1(
        unsafe_root, "context_activation",
    )


def test_source_exit_inventory_is_deterministic() -> None:
    first = build_source_exit_inventory_v1(Path.cwd())
    second = build_source_exit_inventory_v1(Path.cwd())
    assert first == second
    assert len(first["inventory_sha256"]) == 64


def test_dynamic_edge_contract_fingerprint_drift_fails_closed(
    monkeypatch,
) -> None:
    key = next(iter(_DYNAMIC_EDGE_CALLSITE_SHA256))
    monkeypatch.setitem(_DYNAMIC_EDGE_CALLSITE_SHA256, key, ("0" * 64,))

    result = build_source_exit_inventory_v1(Path.cwd())

    assert result["status"] == "FAIL"
    assert (
        result["unresolved_critical_edge_count"] > 0
        or result["stale_dynamic_edge_contract_count"] > 0
    )


def test_direct_path_metrics_detect_unowned_source_paths() -> None:
    source = """
async def unsafe_paths():
    try:
        await gateway.complete_primary()
    except Exception:
        await gateway.complete_primary()
    store.reserve_nonce_from_dispatch_readiness()
    write_full_short_formal_artifacts_v1(())
    observer.mark_post_capture_terminal_failure()

def unsafe_decision():
    controller.authorize_shared_second_slot()
"""
    fixture_path = Path.cwd() / "fixture_direct_path_metrics.py"
    tree = ast.parse(source, filename=str(fixture_path))
    functions = {
        function.function_id: function
        for function in _collect_functions(
            "novel_flywheel.models", fixture_path, tree,
        )
    }
    reachable_functions = set(functions)
    violations = _direct_path_metric_violations_v1(
        repo_root=Path.cwd(),
        functions=functions,
        reachable_functions=reachable_functions,
        function_bindings={
            function_id: {
                "boundary_ids": [],
                "unprotected_path_count": 1,
            }
            for function_id in reachable_functions
        },
        boundary_entries={},
        resolved_calls={},
    )

    assert set(violations) == set(DIRECT_PATH_METRIC_NAMES_V1)
    assert all(violations[name] for name in DIRECT_PATH_METRIC_NAMES_V1)
    assert all(
        row["relative_path"] == "fixture_direct_path_metrics.py"
        and len(row["ast_sha256"]) == 64
        for rows in violations.values()
        for row in rows
    )
