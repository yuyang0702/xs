from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass
from typing import Any

from novel_flywheel.repair_records import RepairRunStore


PUBLIC_REVISION_FIELDS = (
    "status",
    "candidate_hash",
    "gate",
    "review_mode",
    "full_review_reasons",
    "next_action",
    "groups",
)
PUBLIC_GROUP_FIELDS = (
    "group_id",
    "kind",
    "status",
    "decision",
    "message",
    "failures",
    "issue",
    "before",
    "after",
    "related_positions",
    "local_checks",
)
ISSUE_TEXT_FIELDS = (
    "issue_id", "status", "category", "title", "impact", "evidence",
    "suggestion",
)
FAILURE_TEXT_FIELDS = ("code", "message")
POSITION_TEXT_FIELDS = (
    "id", "stable_id", "paragraph_id", "scene_id", "label",
)
POSITION_INT_FIELDS = ("paragraph", "sentence", "start", "end")
LOCAL_CHECK_TEXT_FIELDS = ("code", "message")


@dataclass(frozen=True)
class RevisionOperationError(Exception):
    status_code: int
    code: str
    message: str


class RevisionOperations:
    """Coordinate revision artifacts without making the API router authoritative."""

    def __init__(self, db, projects, workflows) -> None:
        self.db = db
        self.projects = projects
        self.workflows = workflows

    def validate_start(self, project_id: str, issue_ids: list[str]) -> list[str]:
        project = self._project(project_id)
        self._ensure_enabled(project)
        try:
            selected = self.workflows._selected_repair_issue_ids(issue_ids)
        except (TypeError, ValueError):
            raise RevisionOperationError(
                422, "revision_selection_invalid",
                "请选择一至五十个需要处理的问题。",
            ) from None
        protected = self._protected_source(project)
        known_ids = {
            item.get("issue_id")
            for item in protected["issue_ledger"]
            if isinstance(item, dict)
        }
        if any(issue_id not in known_ids for issue_id in selected):
            raise RevisionOperationError(
                422, "revision_selection_invalid",
                "所选问题不在当前受保护稿的问题清单中，请刷新后重试。",
            )
        return selected

    def validate_resume(self, run_id: str) -> tuple[dict[str, Any], list[str]]:
        if self.workflows.recover_short_revision_promotion(run_id):
            return self._run(run_id), []
        authority = self.load_state(run_id)
        run = authority["run"]
        contract = authority["state"]["contract"]
        selected = contract.get("selected_issue_ids")
        try:
            selected = self.workflows._selected_repair_issue_ids(selected)
        except (TypeError, ValueError):
            raise RevisionOperationError(
                409, "revision_run_invalid", "返修记录不完整，请重新开始本次返修。",
            ) from None
        return run, selected

    def load_state(self, run_id: str) -> dict[str, Any]:
        run = self._run(run_id)
        if run.get("workflow") != "short-revision":
            raise RevisionOperationError(
                409, "revision_run_invalid", "该任务不是定向返修任务。",
            )
        project = self._project(str(run["project_id"]))
        self._ensure_enabled(project)
        protected = self._protected_source(project)
        store = RepairRunStore(project.path / "runs" / run_id)
        try:
            state = store.load_resume_state(protected["source_hash"])
        except (OSError, TypeError, ValueError):
            checkpoint = self._read_json_file(
                store.output / RepairRunStore.CHECKPOINT,
            )
            candidate = self._read_text_file(
                store.output / RepairRunStore.CANDIDATE,
            )
            if (
                candidate is not None
                and checkpoint.get("candidate_hash")
                != hashlib.sha256(candidate.encode("utf-8")).hexdigest()
            ):
                raise RevisionOperationError(
                    409, "revision_candidate_changed",
                    "返修候选稿已经变化，请刷新后重试。",
                ) from None
            if checkpoint.get("source_hash") != protected["source_hash"]:
                raise RevisionOperationError(
                    409, "revision_source_changed",
                    "受保护最佳稿已经变化，请重新选择需要处理的问题。",
                ) from None
            raise RevisionOperationError(
                409, "revision_run_invalid",
                "返修记录不完整或已经损坏，请重新开始本次返修。",
            ) from None
        contract = state.get("contract")
        if not isinstance(contract, dict):
            raise RevisionOperationError(
                409, "revision_run_invalid", "返修记录不完整，请重新开始本次返修。",
            )
        if (
            contract.get("manuscript_hash") != protected["source_hash"]
            or contract.get("source_run_id") != protected["run_id"]
            or contract.get("terminal_reviewed_hash") != protected["source_hash"]
        ):
            raise RevisionOperationError(
                409, "revision_source_changed",
                "受保护最佳稿已经变化，请重新选择需要处理的问题。",
            )
        frozen_story = contract.get("story_state")
        current_story = self.workflows.story_states.get(project.id)
        if (
            not isinstance(frozen_story, dict)
            or current_story is None
            or frozen_story.get("revision") != current_story.revision
        ):
            raise RevisionOperationError(
                409, "revision_story_state_changed",
                "作品权威状态已经变化，请重新开始本次返修。",
            )
        if self._normalized(contract.get("passage_locks", [])) != self._normalized(
            self.db.list_locks(project.id)
        ):
            raise RevisionOperationError(
                409, "revision_locks_changed",
                "保护片段已经变化，请重新开始本次返修。",
            )
        return {
            "run": run,
            "project": project,
            "protected": protected,
            "store": store,
            "state": state,
        }

    def read(self, run_id: str) -> dict[str, Any]:
        run = self._run(run_id)
        if run.get("workflow") != "short-revision":
            raise RevisionOperationError(
                409, "revision_run_invalid", "该任务不是定向返修任务。",
            )
        project = self._project(str(run["project_id"]))
        report = self._read_report(project.path / "runs" / run_id)
        groups = report.get("groups", [])
        if isinstance(groups, dict):
            groups = list(groups.values())
        if not isinstance(groups, list):
            groups = []
        public_groups = [
            self.public_group(item)
            for item in groups
            if isinstance(item, dict)
        ]
        return {
            "status": run.get("status"),
            "candidate_hash": report.get("candidate_hash"),
            "gate": report.get("gate"),
            "review_mode": report.get("review_mode"),
            "full_review_reasons": report.get("full_review_reasons", []),
            "next_action": report.get("next_action"),
            "groups": public_groups,
        }

    def decide_group(
        self, run_id: str, group_id: str, decision: str,
        candidate_hash: str,
    ) -> dict[str, Any]:
        return self.workflows.decide_short_revision_group(
            run_id, group_id, decision, candidate_hash,
        )

    async def finalize(self, run_id: str) -> dict[str, Any]:
        return await self.workflows.finalize_short_revision(run_id)

    @staticmethod
    def public_group(item: dict[str, Any]) -> dict[str, Any]:
        result = {
            key: item.get(key)
            for key in PUBLIC_GROUP_FIELDS
        }
        result["issue"] = RevisionOperations._public_record(
            result["issue"], ISSUE_TEXT_FIELDS, bool_fields=("mandatory",),
        )
        result["failures"] = RevisionOperations._public_records(
            result["failures"], FAILURE_TEXT_FIELDS, int_fields=("patch",),
        )
        result["related_positions"] = RevisionOperations._public_records(
            result["related_positions"], POSITION_TEXT_FIELDS,
            int_fields=POSITION_INT_FIELDS,
        )
        result["local_checks"] = RevisionOperations._public_record(
            result["local_checks"], LOCAL_CHECK_TEXT_FIELDS,
            bool_fields=("passed",),
        )
        if (
            result["decision"] is None
            and result["kind"] == "mechanical"
            and result["status"] == "ready_for_confirmation"
        ):
            result["decision"] = "adopted"
        return result

    @staticmethod
    def _public_record(
        value: Any, text_fields: tuple[str, ...],
        *, bool_fields: tuple[str, ...] = (), int_fields: tuple[str, ...] = (),
    ) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        result = {
            key: value[key]
            for key in text_fields
            if isinstance(value.get(key), str)
        }
        result.update({
            key: value[key]
            for key in bool_fields
            if isinstance(value.get(key), bool)
        })
        result.update({
            key: value[key]
            for key in int_fields
            if isinstance(value.get(key), int)
            and not isinstance(value.get(key), bool)
        })
        return result

    @staticmethod
    def _public_records(
        value: Any, text_fields: tuple[str, ...],
        *, bool_fields: tuple[str, ...] = (), int_fields: tuple[str, ...] = (),
    ) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        return [
            projected
            for item in value
            if (projected := RevisionOperations._public_record(
                item, text_fields, bool_fields=bool_fields,
                int_fields=int_fields,
            )) is not None
        ]

    def _project(self, project_id: str):
        try:
            return self.projects.get(project_id)
        except (LookupError, OSError, ValueError):
            raise RevisionOperationError(
                404, "project_not_found", "没有找到这个作品。",
            ) from None

    def _run(self, run_id: str) -> dict[str, Any]:
        run = self.db.get_run(run_id)
        if run is None:
            raise RevisionOperationError(
                404, "run_not_found", "没有找到这次运行。",
            )
        return run

    @staticmethod
    def _ensure_enabled(project) -> None:
        if (
            project.mode != "short"
            or project.metadata.get("optimized_local_review_enabled") is not True
        ):
            raise RevisionOperationError(
                409, "revision_run_invalid",
                "该作品当前不能使用安全定向返修。",
            )

    def _protected_source(self, project) -> dict[str, Any]:
        try:
            return self.workflows._protected_short_revision_source(project)
        except (OSError, TypeError, ValueError):
            raise RevisionOperationError(
                409, "revision_source_changed",
                "当前没有可安全返修的受保护最佳稿，请先完成终审。",
            ) from None

    @staticmethod
    def _read_report(run_path) -> dict[str, Any]:
        try:
            value = json.loads(
                (run_path / "outputs" / RepairRunStore.REPORT).read_text(
                    encoding="utf-8",
                )
            )
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _read_json_file(path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _read_text_file(path) -> str | None:
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return None

    @staticmethod
    def _normalized(value: Any) -> str:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        )
