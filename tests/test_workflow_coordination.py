from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from novel_flywheel.workflow_coordination import WorkflowCoordinator


class FakeService:
    def __init__(self) -> None:
        self.projects = SimpleNamespace(get=self._project)
        self.calls: list[tuple] = []

    @staticmethod
    def _project(project_id: str):
        mode = "long" if project_id.startswith("long") else "short"
        return SimpleNamespace(id=project_id, mode=mode)

    async def _run_in_crewai(self, pipeline):
        self.calls.append(("crewai",))
        return await pipeline()

    async def _short_pipeline(self, project, run_id):
        self.calls.append(("short", project.id, run_id))
        return {"workflow": "short"}

    async def _short_revision_pipeline(self, project, issue_ids, run_id):
        self.calls.append(("revision", project.id, tuple(issue_ids), run_id))
        return {"workflow": "revision"}

    async def _chapter_pipeline(self, project, goal, run_id):
        self.calls.append(("chapter", project.id, goal, run_id))
        return {"workflow": "chapter"}

    async def _long_setup_pipeline(self, project, run_id):
        self.calls.append(("long-setup", project.id, run_id))
        return {"workflow": "long-setup"}

    async def _materials_audit_pipeline(self, project, run_id):
        self.calls.append(("materials-audit", project.id, run_id))
        return {"workflow": "materials-audit"}

    async def _materials_repair_pipeline(self, project, run_id):
        self.calls.append(("materials-repair", project.id, run_id))
        return {"workflow": "materials-repair"}


@pytest.mark.asyncio
async def test_coordinator_owns_public_pipeline_selection(monkeypatch) -> None:
    service = FakeService()
    coordinator = WorkflowCoordinator(service)

    async def material_audit(current_service, project, run_id):
        current_service.calls.append(("materials-audit", project.id, run_id))
        return {"workflow": "materials-audit"}

    async def material_repair(current_service, project, run_id):
        current_service.calls.append(("materials-repair", project.id, run_id))
        return {"workflow": "materials-repair"}

    async def chapter(current_service, project, goal, run_id):
        current_service.calls.append(("chapter", project.id, goal, run_id))
        return {"workflow": "chapter"}

    async def long_setup(current_service, project, run_id):
        current_service.calls.append(("long-setup", project.id, run_id))
        return {"workflow": "long-setup"}

    monkeypatch.setattr(
        "novel_flywheel.workflow_coordination.run_materials_audit",
        material_audit,
    )
    monkeypatch.setattr(
        "novel_flywheel.workflow_coordination.run_materials_repair",
        material_repair,
    )
    monkeypatch.setattr(
        "novel_flywheel.workflow_coordination.run_chapter", chapter,
    )
    monkeypatch.setattr(
        "novel_flywheel.workflow_coordination.run_long_setup", long_setup,
    )

    assert await coordinator.run_short(
        "short-project", use_crewai=True, run_id="run-1",
    ) == {"workflow": "short"}
    assert await coordinator.run_short_revision(
        "short-project", ["issue-1"], run_id="run-2",
    ) == {"workflow": "revision"}
    assert await coordinator.run_chapter(
        "long-project", "goal", use_crewai=False, run_id="run-3",
    ) == {"workflow": "chapter"}
    assert await coordinator.run_long_setup(
        "long-project", use_crewai=False, run_id="run-4",
    ) == {"workflow": "long-setup"}
    assert await coordinator.run_materials_audit(
        "short-project", use_crewai=False, run_id="run-5",
    ) == {"workflow": "materials-audit"}
    assert await coordinator.run_materials_repair(
        "short-project", use_crewai=False, run_id="run-6",
    ) == {"workflow": "materials-repair"}

    assert service.calls == [
        ("crewai",),
        ("short", "short-project", "run-1"),
        ("revision", "short-project", ("issue-1",), "run-2"),
        ("chapter", "long-project", "goal", "run-3"),
        ("long-setup", "long-project", "run-4"),
        ("materials-audit", "short-project", "run-5"),
        ("materials-repair", "short-project", "run-6"),
    ]


@pytest.mark.asyncio
async def test_coordinator_keeps_mode_guards_before_business_pipeline() -> None:
    coordinator = WorkflowCoordinator(FakeService())
    with pytest.raises(ValueError, match="short project"):
        await coordinator.run_short(
            "long-project", use_crewai=False, run_id=None,
        )
    with pytest.raises(ValueError, match="long project"):
        await coordinator.run_long_setup(
            "short-project", use_crewai=False, run_id=None,
        )


def test_workflow_service_public_entries_only_delegate_to_coordinator() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "src" / "novel_flywheel" / "workflows.py"
    ).read_text(encoding="utf-8")
    for pipeline in (
        "_short_pipeline", "_short_revision_pipeline", "_chapter_pipeline",
        "_long_setup_pipeline", "_materials_audit_pipeline",
        "_materials_repair_pipeline",
    ):
        assert f"return await self.{pipeline}" not in source
    assert "async def _materials_audit_pipeline" not in source
    assert "async def _materials_repair_pipeline" not in source
    assert "async def _chapter_pipeline" not in source
    assert "async def _long_setup_pipeline" not in source
