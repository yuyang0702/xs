from __future__ import annotations

"""Closed-world source-exit binder for the exact Full Short runtime.

Discovery and binding are intentionally separate.  The first pass creates
unbound exit and call sites from the whole repository index.  The second pass
propagates boundary state from the real execution roots.  A helper reached by
both protected and unprotected paths remains unbound.
"""

import argparse
import ast
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from novel_flywheel.full_short_runtime_kernel import (
    DEFAULT_FAILURE_BOUNDARY_REGISTRY_V1,
)


FULL_SHORT_RUNTIME_PROOF_DOMAIN_V1 = {
    "schema": "FullShortRuntimeProofDomainV1",
    "version": 1,
    "proof_domain_explicit": True,
    "claim": (
        "All exits crossing registered Short runtime boundaries are typed, "
        "durable, policy-owned, and executable-test-bound."
    ),
    "roots": {
        "tools.canary.first_trustworthy_full_short_runner:execute_full_short_control_plane": "FS.CONTROL.PREFLIGHT",
        "tools.canary.first_trustworthy_full_short_runner:_execute_full_short_control_plane_offline": "FS.CONTROL.PREFLIGHT",
        "tools.canary.first_trustworthy_full_short_runner:run_full_short_workflow_path": "FS.CONTROL.PREFLIGHT",
        "novel_flywheel.workflows:WorkflowService.run_short": "FS.WORKFLOW.SHORT",
    },
    "in_scope": [
        "exact Full Short control plane and task-manager bridge",
        "all Short stage and contract boundaries",
        "provider dispatch, predispatch, nonce, and capture boundaries",
        "central recovery, checkpoint, authority, and terminal boundaries",
    ],
    "out_of_scope": [
        "Long and short revision",
        "unrelated UI/admin entry points",
        "external dependency internals below a registered adapter boundary",
        "retired Hybrid/Selective model-visible paths",
    ],
}


_CALLBACK_TARGETS: dict[tuple[str, str], tuple[str, ...]] = {
    (
        "novel_flywheel.full_short_runtime_kernel:FullShortExecutionKernel.execute_boundary_sync",
        "operation",
    ): (),
    (
        "novel_flywheel.full_short_runtime_kernel:FullShortExecutionKernel.execute_boundary",
        "operation",
    ): (),
    (
        "novel_flywheel.workflow_coordination:WorkflowCoordinator._execute",
        "pipeline",
    ): (
        "novel_flywheel.workflows:WorkflowService._short_pipeline",
    ),
    (
        "novel_flywheel.tasks:RunTaskManager._execute",
        "operation",
    ): (
        "novel_flywheel.workflows:WorkflowService.run_short",
    ),
    (
        "novel_flywheel.tasks:RunTaskManager._execute",
        "terminal_finalizer",
    ): (
        "novel_flywheel.workflows:WorkflowService.bind_full_short_terminal_finalizer.<locals>.finalize",
    ),
    (
        "novel_flywheel.workflows:WorkflowService.bind_full_short_terminal_finalizer.<locals>.finalize",
        "closure",
    ): (
        "tools.canary.first_trustworthy_full_short_runner:_execute_full_short_control_plane_with_capability.<locals>.terminal_closure",
    ),
    (
        "novel_flywheel.workflows:WorkflowService.bind_full_short_terminal_finalizer.<locals>.finalize",
        "post_cleanup_commit",
    ): (
        "tools.canary.first_trustworthy_full_short_runner:_execute_full_short_control_plane_with_capability.<locals>.terminal_closure.<locals>.commit_after_saga_cleanup",
    ),
    (
        "novel_flywheel.providers.http:HttpProvider._before_http_post_attempt",
        "before_dispatch",
    ): (
        "novel_flywheel.full_short_execution:FullShortDispatchLedgerObserverV1.before_http_dispatch",
    ),
    (
        "novel_flywheel.workflows:WorkflowService._execute_protocol_receipt_attempt",
        "operation",
    ): (
        "novel_flywheel.contract_runtime:dispatch_explicit_model_route",
    ),
}


_OBJECT_METHOD_TARGETS: dict[tuple[str, str], tuple[str, ...]] = {
    (
        "novel_flywheel.workflows:WorkflowService.run_short", "run_short",
    ): ("novel_flywheel.workflow_coordination:WorkflowCoordinator.run_short",),
    (
        "novel_flywheel.workflow_coordination:WorkflowCoordinator.run_short",
        "_short_pipeline",
    ): ("novel_flywheel.workflows:WorkflowService._short_pipeline",),
    (
        "tools.canary.first_trustworthy_full_short_runner:_execute_full_short_control_plane_with_capability.<locals>.supervised_operation",
        "run_short",
    ): ("novel_flywheel.workflows:WorkflowService.run_short",),
    (
        "tools.canary.first_trustworthy_full_short_runner:run_full_short_workflow_path",
        "run_short",
    ): ("novel_flywheel.workflows:WorkflowService.run_short",),
    (
        "novel_flywheel.contract_runtime:dispatch_explicit_model_route",
        "complete",
    ): ("novel_flywheel.models:ModelGateway.complete",),
    (
        "novel_flywheel.models:ModelGateway._complete_resolved", "complete",
    ): (
        "novel_flywheel.providers.anthropic:AnthropicAdapter.complete",
        "novel_flywheel.providers.openai_chat:OpenAIChatAdapter.complete",
        "novel_flywheel.providers.openai_responses:OpenAIResponsesAdapter.complete",
    ),
}


_DYNAMIC_EDGE_CALLSITE_SHA256: dict[tuple[str, str], tuple[str, ...]] = {
    ("novel_flywheel.contract_runtime:dispatch_explicit_model_route", "complete"): ("690aab95a085a37fa5206921cccef04c8c661c8dc1faa73447eddf9a4b533930",),
    ("novel_flywheel.full_short_runtime_kernel:FullShortExecutionKernel.execute_boundary", "operation"): ("a87e9308f442543543ba30660fdcfe8ebe4b953e43f6c45c57a7ee156557df56",),
    ("novel_flywheel.full_short_runtime_kernel:FullShortExecutionKernel.execute_boundary_sync", "operation"): ("a87e9308f442543543ba30660fdcfe8ebe4b953e43f6c45c57a7ee156557df56",),
    ("novel_flywheel.models:ModelGateway._complete_resolved", "complete"): ("9a7f144801a99f9d84beb21235abf340cefd13a160745884ae51373ece220d76",),
    ("novel_flywheel.providers.http:HttpProvider._before_http_post_attempt", "before_dispatch"): ("d1ea1675515ab5c8b76a53cc0a7b3c08334a956378eb2fcb257dbf039d98d6c1",),
    ("novel_flywheel.tasks:RunTaskManager._execute", "operation"): ("58bfb9eb2d49b1ce256acb0132994e103f043471736575a0c4498d9d82145355",),
    ("novel_flywheel.tasks:RunTaskManager._execute", "terminal_finalizer"): ("e2630b7c1dc32b812f2fc1818dfa2532f6784d304e1b382c3d1ac190607405ee",),
    ("novel_flywheel.workflow_coordination:WorkflowCoordinator._execute", "pipeline"): ("2946f7a674ec90af88448aee71aa8d2d3079cf3358b09c0e4be3a9d416ebfc9c",),
    ("novel_flywheel.workflow_coordination:WorkflowCoordinator.run_short", "_short_pipeline"): ("4029127d5c7f5b79ffc3e0360622cd6a6b1dd12e51147683ac4e9c523c490eda",),
    ("novel_flywheel.workflows:WorkflowService._execute_protocol_receipt_attempt", "operation"): ("a87e9308f442543543ba30660fdcfe8ebe4b953e43f6c45c57a7ee156557df56",),
    ("novel_flywheel.workflows:WorkflowService.bind_full_short_terminal_finalizer.<locals>.finalize", "closure"): ("5adead1706018889b647d482a843a3b3b6a9ff97b386cc2a52d9ba23db3dbdde",),
    ("novel_flywheel.workflows:WorkflowService.bind_full_short_terminal_finalizer.<locals>.finalize", "post_cleanup_commit"): ("f8924c4c9b21f96f37e24958a849dd59294f96768b7ca53dbf65dbb6a5d1b6e0",),
    ("novel_flywheel.workflows:WorkflowService.run_short", "run_short"): ("cf4610c39361ace3d6522e66744fb47bdf98b311c974c1a97c7e863f29acd650",),
    ("tools.canary.first_trustworthy_full_short_runner:_execute_full_short_control_plane_with_capability.<locals>.supervised_operation", "run_short"): ("8fa7def417be45cfbc9ce9dc4a48e0f88b3f0fff475503bab12e16445d7ea702",),
    ("tools.canary.first_trustworthy_full_short_runner:run_full_short_workflow_path", "run_short"): ("42743dcf9bc2ffeca1a2bd67b4c67c3ad28eced0ea76bdaaf89035fddd6cd562",),
}


_CRITICAL_CALL_NAMES = {
    "complete", "complete_primary", "complete_configured_fallback",
    "complete_route", "complete_with_tools", "complete_with_tools_route",
    "post_stream", "before_http_dispatch",
    "reserve_nonce_from_dispatch_readiness", "authorize_shared_second_slot",
    "commit_project_mutation_authority", "complete_project_mutation",
    "finalize_project_mutation", "write_full_short_formal_artifacts_v1",
    "commit_completion", "operation", "terminal_finalizer", "pipeline",
}


@dataclass(frozen=True)
class _Function:
    function_id: str
    module: str
    qualname: str
    class_name: str | None
    path: Path
    node: ast.FunctionDef | ast.AsyncFunctionDef
    imports: Mapping[str, str]


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _module_name(repo_root: Path, path: Path) -> str:
    source_root = repo_root / "src"
    if path.is_relative_to(source_root):
        return ".".join(path.relative_to(source_root).with_suffix("").parts)
    return ".".join(path.relative_to(repo_root).with_suffix("").parts)


def _imports(tree: ast.Module) -> dict[str, str]:
    result: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                result[alias.asname or alias.name.split(".")[0]] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                result[alias.asname or alias.name] = f"{node.module}:{alias.name}"
    return result


def _collect_functions(
    module: str,
    path: Path,
    tree: ast.Module,
) -> list[_Function]:
    imports = _imports(tree)
    result: list[_Function] = []

    def walk(
        body: Iterable[ast.stmt],
        prefix: str = "",
        class_name: str | None = None,
    ) -> None:
        for node in body:
            if isinstance(node, ast.ClassDef):
                qualname = f"{prefix}.{node.name}" if prefix else node.name
                walk(node.body, qualname, node.name)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualname = f"{prefix}.{node.name}" if prefix else node.name
                result.append(_Function(
                    function_id=f"{module}:{qualname}", module=module,
                    qualname=qualname, class_name=class_name, path=path,
                    node=node, imports=imports,
                ))
                nested_prefix = f"{qualname}.<locals>"
                walk(node.body, nested_prefix, None)
            else:
                for _field, value in ast.iter_fields(node):
                    if isinstance(value, list) and value and all(
                        isinstance(item, ast.stmt) for item in value
                    ):
                        walk(value, prefix, class_name)
                    elif isinstance(value, ast.stmt):
                        walk((value,), prefix, class_name)

    walk(tree.body)
    return result


class _BodyVisitor(ast.NodeVisitor):
    def __init__(self, root: ast.AST) -> None:
        self.root = root
        self.calls: list[ast.Call] = []
        self.exits: list[tuple[str, ast.AST]] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node is self.root:
            self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        if node is self.root:
            self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return

    def visit_Raise(self, node: ast.Raise) -> None:
        self.exits.append(("raise", node))
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        self.exits.append(("except_handler", node))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        self.calls.append(node)
        name = _call_name(node)
        if name in {"_require", "require"}:
            self.exits.append(("guard_call", node))
        self.generic_visit(node)

    def visit_Return(self, node: ast.Return) -> None:
        if node.value is not None and isinstance(
            node.value, (ast.Tuple, ast.Dict, ast.Call)
        ):
            dump = ast.dump(node.value, include_attributes=False).lower()
            if any(token in dump for token in ("error", "failure", "rejected")):
                self.exits.append(("typed_error_result", node))
        self.generic_visit(node)


def _call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return "<dynamic>"


def _decorated_boundary(function: _Function) -> str | None:
    for decorator in function.node.decorator_list:
        if not (
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Name)
            and decorator.func.id == "full_short_boundary_entry"
            and len(decorator.args) == 1
            and isinstance(decorator.args[0], ast.Constant)
            and isinstance(decorator.args[0].value, str)
        ):
            continue
        return decorator.args[0].value
    return None


def _index(repo_root: Path) -> dict[str, _Function]:
    paths = sorted((repo_root / "src" / "novel_flywheel").rglob("*.py"))
    paths.append(repo_root / "tools" / "canary" / "first_trustworthy_full_short_runner.py")
    result: dict[str, _Function] = {}
    for path in paths:
        module = _module_name(repo_root, path)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for function in _collect_functions(module, path, tree):
            result[function.function_id] = function
    return result


def _same_scope_candidates(
    function: _Function,
    name: str,
    functions: Mapping[str, _Function],
) -> tuple[str, ...]:
    prefixes = []
    prefixes.append(function.qualname + ".<locals>.")
    parts = function.qualname.split(".<locals>.")
    if len(parts) > 1:
        prefixes.append(parts[0] + ".<locals>.")
    if function.class_name:
        prefixes.append(function.class_name + ".")
    prefixes.append("")
    for prefix in prefixes:
        candidate = f"{function.module}:{prefix}{name}"
        if candidate in functions:
            return (candidate,)
    return ()


def _resolve_call(
    function: _Function,
    call: ast.Call,
    functions: Mapping[str, _Function],
) -> tuple[tuple[str, ...], str | None]:
    name = _call_name(call)
    contract = _CALLBACK_TARGETS.get((function.function_id, name))
    if contract is None:
        contract = _OBJECT_METHOD_TARGETS.get((function.function_id, name))
    if contract is not None:
        callsite_sha256 = hashlib.sha256(
            ast.dump(call, include_attributes=False).encode("utf-8")
        ).hexdigest()
        allowed_callsites = _DYNAMIC_EDGE_CALLSITE_SHA256.get(
            (function.function_id, name), (),
        )
        if callsite_sha256 not in allowed_callsites:
            return (), "dynamic_edge_contract_stale"
        missing = tuple(target for target in contract if target not in functions)
        return tuple(target for target in contract if target in functions), (
            "dynamic_contract_target_missing" if missing else None
        )
    if isinstance(call.func, ast.Name):
        local = _same_scope_candidates(function, call.func.id, functions)
        if local:
            return local, None
        imported = function.imports.get(call.func.id)
        if imported and ":" in imported and imported in functions:
            return (imported,), None
        if name in _CRITICAL_CALL_NAMES:
            return (), "unresolved_critical_name_call"
        return (), None
    if isinstance(call.func, ast.Attribute):
        value = call.func.value
        if (
            isinstance(value, ast.Name)
            and value.id in {"self", "cls"}
            and function.class_name
        ):
            target = f"{function.module}:{function.class_name}.{name}"
            if target in functions:
                return (target,), None
        if isinstance(value, ast.Name):
            imported = function.imports.get(value.id)
            if imported and ":" not in imported:
                target = f"{imported}:{name}"
                if target in functions:
                    return (target,), None
            if imported and ":" in imported:
                module, symbol = imported.split(":", 1)
                target = f"{module}:{symbol}.{name}"
                if target in functions:
                    return (target,), None
        candidates = tuple(sorted(
            key for key, candidate in functions.items()
            if candidate.qualname.endswith("." + name)
        ))
        if len(candidates) == 1:
            return candidates, None
        if name in _CRITICAL_CALL_NAMES:
            return (), "unresolved_critical_attribute_call"
        return (), None
    if name in _CRITICAL_CALL_NAMES:
        return (), "unresolved_critical_dynamic_call"
    return (), None


def bind_exit_states_v1(
    *,
    graph: Mapping[str, set[str]],
    roots: Mapping[str, str | None],
    boundary_entries: Mapping[str, str],
    exits_by_function: Mapping[str, set[str]],
) -> dict[str, dict[str, object]]:
    states: dict[str, set[str | None]] = {}
    queue: list[tuple[str, str | None]] = []
    for function_id, state in roots.items():
        queue.append((function_id, boundary_entries.get(function_id, state)))
    seen: set[tuple[str, str | None]] = set()
    while queue:
        function_id, state = queue.pop(0)
        state = boundary_entries.get(function_id, state)
        key = (function_id, state)
        if key in seen:
            continue
        seen.add(key)
        states.setdefault(function_id, set()).add(state)
        for target in sorted(graph.get(function_id, set())):
            queue.append((target, boundary_entries.get(target, state)))

    result: dict[str, dict[str, object]] = {}
    for function_id, exit_ids in exits_by_function.items():
        values = states.get(function_id, set())
        protected = {value for value in values if value is not None}
        unprotected = int(None in values)
        disposition = (
            "UNBOUND" if unprotected or not values
            else "BOUNDARY_ID" if len(protected) == 1
            else "INTERNAL_CONTAINED_NON_BOUNDARY"
        )
        for exit_id in exit_ids:
            result[exit_id] = {
                "function_id": function_id,
                "disposition": disposition,
                "boundary_ids": sorted(protected),
                "protected_path_count": len(protected),
                "unprotected_path_count": unprotected,
            }
    return result


def build_source_exit_inventory_v1(repo_root: Path) -> dict[str, object]:
    repo_root = repo_root.resolve()
    functions = _index(repo_root)
    boundary_entries = {
        function_id: boundary
        for function_id, function in functions.items()
        if (boundary := _decorated_boundary(function)) is not None
    }
    registry_entries = {
        boundary.entry_function: boundary.boundary_id
        for boundary in DEFAULT_FAILURE_BOUNDARY_REGISTRY_V1.boundaries
    }
    bad_registry_wrappers = sorted(
        function_id for function_id, boundary_id in registry_entries.items()
        if boundary_entries.get(function_id) != boundary_id
    )
    roots = dict(FULL_SHORT_RUNTIME_PROOF_DOMAIN_V1["roots"])
    missing_roots = sorted(set(roots) - set(functions))

    graph: dict[str, set[str]] = {key: set() for key in functions}
    exits_by_function: dict[str, set[str]] = {}
    exit_rows: dict[str, dict[str, object]] = {}
    unresolved_by_function: dict[str, list[dict[str, object]]] = {}
    observed_dynamic_contracts: set[tuple[str, str]] = set()
    for function_id, function in functions.items():
        visitor = _BodyVisitor(function.node)
        visitor.visit(function.node)
        for ordinal, (kind, node) in enumerate(visitor.exits, 1):
            semantic = {
                "function_id": function_id,
                "kind": kind,
                "ordinal": ordinal,
                "ast_sha256": hashlib.sha256(
                    ast.dump(node, include_attributes=False).encode("utf-8")
                ).hexdigest(),
            }
            exit_id = _sha(semantic)
            exits_by_function.setdefault(function_id, set()).add(exit_id)
            exit_rows[exit_id] = {
                **semantic,
                "exit_id": exit_id,
                "relative_path": function.path.relative_to(repo_root).as_posix(),
                "line": getattr(node, "lineno", None),
                "column": getattr(node, "col_offset", None),
            }
        for call in visitor.calls:
            contract_key = (function_id, _call_name(call))
            callsite_sha256 = hashlib.sha256(
                ast.dump(call, include_attributes=False).encode("utf-8")
            ).hexdigest()
            if (
                contract_key in _DYNAMIC_EDGE_CALLSITE_SHA256
                and callsite_sha256
                in _DYNAMIC_EDGE_CALLSITE_SHA256[contract_key]
            ):
                observed_dynamic_contracts.add(contract_key)
            targets, unresolved = _resolve_call(function, call, functions)
            graph[function_id].update(targets)
            if unresolved:
                unresolved_by_function.setdefault(function_id, []).append({
                    "call_name": _call_name(call),
                    "line": getattr(call, "lineno", None),
                    "ast_sha256": hashlib.sha256(
                        ast.dump(call, include_attributes=False).encode("utf-8")
                    ).hexdigest(),
                    "reason": unresolved,
                })

    bindings = bind_exit_states_v1(
        graph=graph,
        roots={key: value for key, value in roots.items() if key in functions},
        boundary_entries=boundary_entries,
        exits_by_function=exits_by_function,
    )
    reachable_functions = {
        str(value["function_id"]) for value in bindings.values()
        if value["protected_path_count"] or value["unprotected_path_count"]
    }
    # Functions without an exit still matter for boundary reachability and
    # unresolved critical calls, so repeat the same propagation with markers.
    function_markers = {key: {"fn:" + key} for key in functions}
    function_states = bind_exit_states_v1(
        graph=graph,
        roots={key: value for key, value in roots.items() if key in functions},
        boundary_entries=boundary_entries,
        exits_by_function=function_markers,
    )
    reachable_functions.update(
        str(value["function_id"]) for value in function_states.values()
        if value["protected_path_count"] or value["unprotected_path_count"]
    )
    reachable_boundary_ids = {
        boundary_entries[function_id]
        for function_id in reachable_functions
        if function_id in boundary_entries
    }
    registered_boundary_ids = set(registry_entries.values())
    unreachable_boundaries = sorted(
        registered_boundary_ids - reachable_boundary_ids
    )
    reachable_exits = sorted(
        exit_id for exit_id, binding in bindings.items()
        if binding["function_id"] in reachable_functions
    )
    unbound = [
        exit_id for exit_id in reachable_exits
        if bindings[exit_id]["disposition"] == "UNBOUND"
    ]
    unresolved = sorted(
        [
            {"function_id": function_id, **item}
            for function_id, items in unresolved_by_function.items()
            if function_id in reachable_functions
            for item in items
        ],
        key=lambda item: (
            str(item["function_id"]), int(item["line"] or 0),
            str(item["ast_sha256"]),
        ),
    )
    stale_dynamic_contracts = sorted(
        (set(_CALLBACK_TARGETS) | set(_OBJECT_METHOD_TARGETS))
        - observed_dynamic_contracts
    )
    exits = [
        {**exit_rows[exit_id], **bindings[exit_id]}
        for exit_id in reachable_exits
    ]
    failure_summary = {
        "missing_execution_roots": missing_roots,
        "registry_entries_without_exact_wrapper": bad_registry_wrappers,
        "unreachable_registered_boundaries": unreachable_boundaries,
        "unbound_exit_ids": unbound[:20],
        "unresolved_critical_edges": unresolved[:20],
        "stale_dynamic_edge_contracts": [
            {"function_id": item[0], "call_name": item[1]}
            for item in stale_dynamic_contracts[:20]
        ],
    }
    passed = not any((
        missing_roots, bad_registry_wrappers, unreachable_boundaries,
        unbound, unresolved, stale_dynamic_contracts,
    ))
    identity = {
        "proof_domain": FULL_SHORT_RUNTIME_PROOF_DOMAIN_V1,
        "registry_identity_sha256": (
            DEFAULT_FAILURE_BOUNDARY_REGISTRY_V1.identity_sha256
        ),
        "exits": exits,
        "unresolved_critical_edges": unresolved,
    }
    return {
        "schema": "FullShortSourceFailureExitInventoryV1",
        "version": 1,
        "status": "PASS" if passed else "FAIL",
        "proof_domain_explicit": True,
        "source_failure_exit_count": len(exits),
        "unbound_source_failure_exit_count": len(unbound),
        "unresolved_critical_edge_count": len(unresolved),
        "stale_dynamic_edge_contract_count": len(stale_dynamic_contracts),
        "unreachable_registered_boundary_count": len(unreachable_boundaries),
        "registry_entry_without_exact_wrapper_count": len(bad_registry_wrappers),
        "reachable_function_count": len(reachable_functions),
        "registered_boundary_count": len(registered_boundary_ids),
        "failure_summary": failure_summary,
        "exits": exits,
        "unresolved_critical_edges": unresolved,
        "inventory_sha256": _sha(identity),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = build_source_exit_inventory_v1(args.repo_root)
    text = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
