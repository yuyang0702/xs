from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from novel_flywheel.materials_workflow import (
    run_materials_audit,
    run_materials_repair,
)
from novel_flywheel.long_workflow import run_chapter, run_long_setup


Pipeline = Callable[[], Awaitable[dict]]


@dataclass(frozen=True)
class WorkflowCoordinator:
    """Single public orchestration boundary for every project workflow.

    Business validators and artifact authorities remain on ``WorkflowService``;
    this coordinator owns project-mode checks, optional CrewAI execution, and
    selection of the one authoritative pipeline.  It deliberately contains no
    parsing, retry, promotion, or narrative policy.
    """

    service: Any

    async def _execute(self, pipeline: Pipeline, *, use_crewai: bool) -> dict:
        if use_crewai:
            return await self.service._run_in_crewai(pipeline)
        return await pipeline()

    async def run_short(
        self, project_id: str, *, use_crewai: bool, run_id: str | None,
    ) -> dict:
        project = self.service.projects.get(project_id)
        if project.mode != "short":
            raise ValueError("Short-story workflow requires a short project")
        return await self._execute(
            lambda: self.service._short_pipeline(project, run_id),
            use_crewai=use_crewai,
        )

    async def run_short_revision(
        self, project_id: str, issue_ids: list[str], *, run_id: str | None,
    ) -> dict:
        project = self.service.projects.get(project_id)
        if project.mode != "short":
            raise ValueError("定向返修目前只支持短篇作品")
        return await self.service._short_revision_pipeline(
            project, list(issue_ids), run_id,
        )

    async def run_chapter(
        self, project_id: str, chapter_goal: str, *, use_crewai: bool,
        run_id: str | None,
    ) -> dict:
        project = self.service.projects.get(project_id)
        if project.mode != "long":
            raise ValueError("Long chapter workflow requires a long project")
        return await self._execute(
            lambda: run_chapter(self.service, project, chapter_goal, run_id),
            use_crewai=use_crewai,
        )

    async def run_long_setup(
        self, project_id: str, *, use_crewai: bool, run_id: str | None,
    ) -> dict:
        project = self.service.projects.get(project_id)
        if project.mode != "long":
            raise ValueError("Long setup workflow requires a long project")
        return await self._execute(
            lambda: run_long_setup(self.service, project, run_id),
            use_crewai=use_crewai,
        )

    async def run_materials_audit(
        self, project_id: str, *, use_crewai: bool, run_id: str | None,
    ) -> dict:
        project = self.service.projects.get(project_id)
        return await self._execute(
            lambda: run_materials_audit(self.service, project, run_id),
            use_crewai=use_crewai,
        )

    async def run_materials_repair(
        self, project_id: str, *, use_crewai: bool, run_id: str | None,
    ) -> dict:
        project = self.service.projects.get(project_id)
        return await self._execute(
            lambda: run_materials_repair(self.service, project, run_id),
            use_crewai=use_crewai,
        )
