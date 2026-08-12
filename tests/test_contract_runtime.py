from __future__ import annotations
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ConfigDict

from novel_flywheel.contract_runtime import (
    ExecutableContractSpec,
    contract_route_capacity_plan,
    execute_contract_runtime,
    execute_model_route_runtime,
    execute_text_runtime,
)
from novel_flywheel.generated_artifacts import (
    ARTIFACT_CONTRACT_REGISTRY,
    ArtifactContractRegistration,
)
from novel_flywheel.structured_artifacts import StructuredArtifactContract


class MessageArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    message: str


CONTRACT = StructuredArtifactContract(
    name="interview_planning",
    version=1,
    schema=MessageArtifact.model_json_schema(),
)


def test_route_capacity_plan_uses_explicit_capable_routes_only() -> None:
    class DB:
        @staticmethod
        def get_role_binding(role):
            assert role == "planning"
            return {
                "primary_model_id": "small",
                "fallback_provider_id": "provider",
                "fallback_model_id": "large",
            }

        @staticmethod
        def get_model(model_id):
            return {
                "context_window": 4_096 if model_id == "small" else 32_768,
                "max_output_tokens": 2_048,
            }

    plan = contract_route_capacity_plan(
        DB(), SimpleNamespace(), role="planning",
        output_reserve_tokens=2_048,
        context_utilization=0.75,
        unknown_context_tokens=16_384,
    )

    assert plan.primary_input_token_limit == 1_024
    assert plan.fallback_input_token_limit == 22_528
    assert plan.attempt_routes(900) == (
        "primary", "primary", "configured_fallback", "configured_fallback",
    )
    assert plan.attempt_routes(2_000) == (
        "configured_fallback", "configured_fallback",
    )
    with pytest.raises(ValueError, match="exceeds every configured"):
        plan.attempt_routes(30_000)


def normalize(value):
    try:
        return MessageArtifact.model_validate(value).model_dump(mode="json")
    except ValueError:
        return None


def execution_spec(
    *, contract_name: str = "interview_planning",
    contract: StructuredArtifactContract = CONTRACT,
    domain_validator=lambda payload: payload,
    retry_domain_failures: bool = False,
) -> ExecutableContractSpec:
    if contract.name != contract_name:
        contract = contract.model_copy(update={"name": contract_name})
    return ExecutableContractSpec(
        contract_name=contract_name,
        structured_contract=contract,
        semantic_normalizer=normalize,
        domain_validator=domain_validator,
        retry_domain_failures=retry_domain_failures,
    )


def test_business_services_cannot_add_private_model_route_executors() -> None:
    """All business services must enter the shared model route runtime."""

    source_root = Path(__file__).parents[1] / "src" / "novel_flywheel"
    route_methods = {
        "complete", "complete_primary", "complete_configured_fallback",
        "complete_structured", "complete_with_tools", "complete_route",
        "complete_with_tools_route",
    }
    discovered = set()
    for source_path in source_root.rglob("*.py"):
        relative = source_path.relative_to(source_root).as_posix()
        if relative == "models.py" or relative.startswith("providers/"):
            continue
        tree = ast.parse(
            source_path.read_text(encoding="utf-8"), filename=str(source_path),
        )
        parents = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node
        for call in ast.walk(tree):
            if not (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr in route_methods
            ):
                continue
            owner = call
            while owner is not None and not isinstance(
                owner, (ast.FunctionDef, ast.AsyncFunctionDef),
            ):
                owner = parents.get(owner)
            discovered.add((
                relative, getattr(owner, "name", "<module>"), call.func.attr,
            ))

    assert discovered == set()


def test_contract_runtime_cannot_own_novel_business_or_mutate_project_state() -> None:
    """Keep the shared kernel below every narrative/business validator.

    The refactor is allowed to consolidate representation, route selection,
    and bounded recovery.  It is not allowed to absorb planning, story-state,
    quality, material, or formal-promotion policy merely to reduce call sites.
    """

    source_path = (
        Path(__file__).parents[1] / "src" / "novel_flywheel"
        / "contract_runtime.py"
    )
    tree = ast.parse(
        source_path.read_text(encoding="utf-8"), filename=str(source_path),
    )
    imported_modules = set()
    call_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported_modules.add(node.module or "")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                call_names.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                call_names.add(node.func.attr)

    forbidden_modules = {
        "novel_flywheel.story_state",
        "novel_flywheel.storage",
        "novel_flywheel.db",
        "novel_flywheel.workflows",
        "novel_flywheel.planning_compiler",
        "novel_flywheel.planning_semantics",
        "novel_flywheel.execution_manifest",
        "novel_flywheel.quality",
        "novel_flywheel.outlines",
        "novel_flywheel.material_impacts",
    }
    assert imported_modules.isdisjoint(forbidden_modules)
    assert call_names.isdisjoint({
        "atomic_write", "atomic_write_bytes", "create_candidate", "commit",
        "update_run", "save_workflow_node_checkpoint",
    })


@pytest.mark.asyncio
async def test_model_route_runtime_owns_exact_tool_fallback_and_route_budgets() -> None:
    class Toolbox:
        @staticmethod
        def prepare_fallback(_error):
            return "retained proposal hashes"

    class Gateway:
        def __init__(self):
            self.calls = []

        @staticmethod
        def has_configured_fallback(role):
            assert role == "planning"
            return True

        async def complete_with_tools_route(
            self, route, role, system, user, toolbox, fallback_context, **kwargs,
        ):
            self.calls.append((route, user, kwargs["max_output_tokens"]))
            if route == "primary":
                raise ConnectionError("primary transport failed")
            return SimpleNamespace(
                text="tool work completed",
                receipt={"execution_mode": "native_tools"},
            )

    gateway = Gateway()
    result = await execute_model_route_runtime(
        gateway,
        role="planning",
        system="immutable tool task",
        user="confirmed inputs",
        route_max_output_tokens={
            "primary": 111,
            "configured_fallback": 222,
        },
        same_route_attempts=1,
        fallback_attempts=1,
        toolbox=Toolbox(),
        fallback_context=lambda: "fallback facts",
    )

    assert [item[0] for item in gateway.calls] == [
        "primary", "configured_fallback",
    ]
    assert [item[2] for item in gateway.calls] == [111, 222]
    assert "retained proposal hashes" in gateway.calls[1][1]
    assert result.attempt.route == "configured_fallback"
    assert result.model_response.receipt["runtime_selected_route"] == (
        "configured_fallback"
    )


@pytest.mark.asyncio
async def test_contract_runtime_retries_same_task_on_same_explicit_route() -> None:
    class Gateway:
        def __init__(self):
            self.calls = []
            self.outputs = [
                '{"legacy_message":"preserved"}',
                '{"message":"preserved"}',
            ]

        async def complete_primary(self, role, system, user, **kwargs):
            self.calls.append((role, system, user, kwargs))
            return SimpleNamespace(text=self.outputs.pop(0), receipt={})

    gateway = Gateway()
    result = await execute_contract_runtime(
        gateway,
        role="planning",
        system="analyze once",
        user="private input",
        execution_spec=execution_spec(),
        fallback_attempts=0,
    )

    assert result.payload == {"message": "preserved"}
    assert [call[0] for call in gateway.calls] == ["planning", "planning"]
    assert gateway.calls[0][1:3] == ("analyze once", "private input")
    assert "deterministically converted" in gateway.calls[1][1]
    assert gateway.calls[1][2] == "private input"


@pytest.mark.asyncio
async def test_contract_runtime_retries_original_task_when_no_semantics_exist() -> None:
    class Gateway:
        def __init__(self):
            self.calls = []
            self.outputs = ["", '{"message":"recovered"}']

        async def complete_primary(self, role, system, user, **kwargs):
            self.calls.append((system, user))
            return SimpleNamespace(text=self.outputs.pop(0), receipt={})

    gateway = Gateway()
    result = await execute_contract_runtime(
        gateway,
        role="planning",
        system="original system",
        user="original task",
        execution_spec=execution_spec(),
        fallback_attempts=0,
    )

    assert result.payload == {"message": "recovered"}
    assert gateway.calls[0] == ("original system", "original task")
    assert gateway.calls[1][1] == "original task"
    assert gateway.calls[1][0].startswith("original system")
    assert "return the specified JSON" in gateway.calls[1][0]


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_contract_runtime_uses_declared_fallback_without_hidden_auto_route() -> None:
    class Gateway:
        def __init__(self):
            self.routes = []

        def has_configured_fallback(self, role):
            return True

        async def complete_route(self, route, role, system, user, **kwargs):
            self.routes.append(route)
            if route == "primary":
                raise RuntimeError("primary transport unavailable")
            return SimpleNamespace(text='{"message":"fallback"}', receipt={})

    gateway = Gateway()
    result = await execute_contract_runtime(
        gateway,
        role="planning",
        system="system",
        user="input",
        execution_spec=execution_spec(),
        same_route_attempts=2,
        fallback_attempts=1,
    )

    assert gateway.routes == ["primary", "primary", "configured_fallback"]
    assert result.payload["message"] == "fallback"


@pytest.mark.asyncio
async def test_contract_runtime_never_rewrites_domain_semantic_failure() -> None:
    class Gateway:
        def __init__(self):
            self.calls = 0

        async def complete_primary(self, role, system, user, **kwargs):
            self.calls += 1
            return SimpleNamespace(text='{"message":"valid shape"}', receipt={})

    gateway = Gateway()

    with pytest.raises(ValueError, match="domain invariant"):
        await execute_contract_runtime(
            gateway,
            role="planning",
            system="system",
            user="input",
            execution_spec=execution_spec(
                domain_validator=lambda _payload: (_ for _ in ()).throw(
                    ValueError("domain invariant")
                ),
            ),
            fallback_attempts=0,
        )

    assert gateway.calls == 1


@pytest.mark.asyncio
async def test_text_runtime_keeps_prose_free_form_and_retries_business_failure() -> None:
    class Gateway:
        def __init__(self):
            self.calls = []
            self.outputs = ["rewritten without protected fact", "rewritten with LOCKED"]

        async def complete_primary(self, role, system, user, **kwargs):
            self.calls.append((role, system, user))
            return SimpleNamespace(text=self.outputs.pop(0), receipt={})

    gateway = Gateway()
    result = await execute_text_runtime(
        gateway,
        role="line_edit",
        system="edit prose",
        user="source prose and LOCKED fact",
        domain_validator=lambda text: (
            text if "LOCKED" in text else (_ for _ in ()).throw(
                ValueError("locked fact missing")
            )
        ),
        retry_domain_failures=True,
        fallback_attempts=0,
    )

    assert result.text == "rewritten with LOCKED"
    assert len(gateway.calls) == 2
    assert gateway.calls[0][1:] == ("edit prose", "source prose and LOCKED fact")
    assert "Runtime-owned business validation" in gateway.calls[1][1]


@pytest.mark.asyncio
async def test_text_runtime_uses_explicit_fallback_without_hidden_auto_route() -> None:
    class Gateway:
        def __init__(self):
            self.routes = []

        def has_configured_fallback(self, role):
            return True

        async def complete_route(self, route, role, system, user, **kwargs):
            self.routes.append(route)
            if route == "primary":
                raise RuntimeError("primary unavailable")
            return SimpleNamespace(text="free-form fallback prose", receipt={})

    gateway = Gateway()
    result = await execute_text_runtime(
        gateway,
        role="planning",
        system="write an outline",
        user="original brief",
        same_route_attempts=2,
        fallback_attempts=1,
    )

    assert result.text == "free-form fallback prose"
    assert gateway.routes == ["primary", "primary", "configured_fallback"]


@pytest.mark.asyncio
async def test_text_runtime_transport_retry_does_not_claim_business_failure() -> None:
    class Gateway:
        def __init__(self):
            self.systems = []

        async def complete_primary(self, role, system, user, **kwargs):
            self.systems.append(system)
            if len(self.systems) == 1:
                raise TimeoutError("transport interrupted")
            return SimpleNamespace(text="unchanged prose", receipt={})

    gateway = Gateway()
    result = await execute_text_runtime(
        gateway,
        role="line_edit",
        system="edit prose",
        user="source prose",
        fallback_attempts=0,
    )

    assert result.text == "unchanged prose"
    assert gateway.systems == ["edit prose", "edit prose"]


@pytest.mark.asyncio
async def test_runtime_never_uses_implicit_primary_when_fallback_is_configured() -> None:
    class Gateway:
        def __init__(self):
            self.hidden_auto_calls = 0
            self.fallback_calls = 0

        def has_configured_fallback(self, role):
            return True

        async def complete(self, *args, **kwargs):
            self.hidden_auto_calls += 1
            raise AssertionError("generic complete may hide fallback")

        async def complete_configured_fallback(self, role, system, user, **kwargs):
            self.fallback_calls += 1
            return SimpleNamespace(text="explicit fallback prose", receipt={})

    gateway = Gateway()
    result = await execute_text_runtime(
        gateway,
        role="planning",
        system="write",
        user="brief",
        same_route_attempts=2,
        fallback_attempts=1,
    )

    assert result.text == "explicit fallback prose"
    assert gateway.hidden_auto_calls == 0
    assert gateway.fallback_calls == 1


@pytest.mark.asyncio
async def test_structured_runtime_cannot_exceed_registered_route_ladder(
    monkeypatch,
) -> None:
    contract_name = "test_no_model_fallback"
    monkeypatch.setitem(
        ARTIFACT_CONTRACT_REGISTRY,
        contract_name,
        ArtifactContractRegistration(
            name=contract_name,
            phase="runtime",
            semantic_authority="test-only strict route authority",
            recovery_ladder=(
                "exact_json", "local_syntax_repair",
                "semantic_protocol_retry", "minimal_regeneration",
            ),
        ),
    )

    class Gateway:
        def __init__(self):
            self.routes = []

        def has_configured_fallback(self, role):
            return True

        async def complete_route(self, route, role, system, user, **kwargs):
            self.routes.append(route)
            raise RuntimeError("route unavailable")

    gateway = Gateway()
    with pytest.raises(RuntimeError, match="route unavailable"):
        await execute_contract_runtime(
            gateway,
            role="planning",
            system="system",
            user="input",
            execution_spec=execution_spec(contract_name=contract_name),
            same_route_attempts=2,
            fallback_attempts=2,
        )

    assert gateway.routes == ["primary", "primary"]


@pytest.mark.asyncio
async def test_contract_runtime_can_validate_workflow_owned_route_attempts() -> None:
    """Workflow stages may keep skills/capacity while sharing one converter."""

    class Gateway:
        async def complete(self, *_args, **_kwargs):
            raise AssertionError("the workflow-owned executor must own transport")

    calls = []

    async def execute(attempt, role, system, user, max_output_tokens, contract):
        calls.append((
            attempt.route, role, system, user, max_output_tokens, contract.name,
        ))
        return '{"message":"preserved business value"}'

    result = await execute_contract_runtime(
        Gateway(),
        role="planning",
        system="system",
        user="same immutable task",
        execution_spec=execution_spec(),
        max_output_tokens=700,
        attempt_routes=("primary",),
        attempt_executor=execute,
    )

    assert result.payload == {"message": "preserved business value"}
    assert calls == [(
        "primary", "planning", "system", "same immutable task", 700,
        "interview_planning",
    )]


@pytest.mark.asyncio
async def test_structured_runtime_rejects_undeclared_domain_regeneration(
    monkeypatch,
) -> None:
    contract_name = "test_no_domain_regeneration"
    monkeypatch.setitem(
        ARTIFACT_CONTRACT_REGISTRY,
        contract_name,
        ArtifactContractRegistration(
            name=contract_name,
            phase="runtime",
            semantic_authority="test-only semantic authority",
            recovery_ladder=(
                "exact_json", "local_syntax_repair",
                "semantic_protocol_retry",
            ),
        ),
    )

    with pytest.raises(ValueError, match="domain regeneration"):
        execution_spec(
            contract_name=contract_name,
            retry_domain_failures=True,
        )


@pytest.mark.asyncio
async def test_runtime_rejects_wire_schema_version_drift_before_model_call() -> None:
    class Gateway:
        def __init__(self):
            self.calls = 0

        async def complete_primary(self, *args, **kwargs):
            self.calls += 1
            return SimpleNamespace(text='{"message":"unsafe"}', receipt={})

    gateway = Gateway()
    wrong_version = StructuredArtifactContract(
        name=CONTRACT.name,
        version=2,
        schema=CONTRACT.json_schema,
    )

    with pytest.raises(ValueError, match="version does not match"):
        execution_spec(contract=wrong_version)

    assert gateway.calls == 0
