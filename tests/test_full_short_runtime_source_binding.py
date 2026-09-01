from __future__ import annotations

from pathlib import Path

from tools.diagnostics.bind_full_short_runtime_source_exits import (
    _DYNAMIC_EDGE_CALLSITE_SHA256,
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
