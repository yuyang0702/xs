from __future__ import annotations

import uuid
from typing import Any

from novel_flywheel.quality_records import reconcile_legacy_checkpoint


ROLE_LABELS = {
    "high_quality_anchor": "高质量参考",
    "ordinary_anchor": "普通水平参考",
    "known_problem": "已知问题参考",
    "historical_baseline": "本项目历史基线",
    "before_after_pair": "修改前后对照",
}


class QualityReferenceService:
    def __init__(self, db, references, projects) -> None:
        self.db = db
        self.references = references
        self.projects = projects

    def recommend(self, project_id: str, profile_id: str) -> dict[str, Any]:
        project = self.projects.get(project_id)
        active = self.list_group(project_id, profile_id)
        active_ids = {item["id"] for item in active["items"]}
        recommendations = self._reference_candidates(project_id)
        recommendations.extend(self._history_candidates(project))
        seen = set()
        recommendations = [
            item for item in recommendations
            if not (item["id"] in seen or seen.add(item["id"]))
        ]
        for item in recommendations:
            item["status"] = "confirmed" if item["id"] in active_ids else "recommended"
        present_roles = {item["role"] for item in recommendations}
        return {
            "project_id": project_id,
            "profile_id": profile_id,
            "model_called": False,
            "active_group": active,
            "recommendations": recommendations,
            "missing_roles": [
                {"role": role, "label": label}
                for role, label in ROLE_LABELS.items() if role not in present_roles
            ],
            "message": "推荐不会自动生效，请确认后再用于人工评分校准。",
        }

    def confirm(
        self, project_id: str, profile_id: str, *,
        accepted_ids: list[str], rejected_ids: list[str],
    ) -> dict[str, Any]:
        if set(accepted_ids) & set(rejected_ids):
            raise ValueError("同一条参考不能同时确认和拒绝")
        candidates = {
            item["id"]: item
            for item in self.recommend(project_id, profile_id)["recommendations"]
        }
        unknown = (set(accepted_ids) | set(rejected_ids)) - set(candidates)
        if unknown:
            raise ValueError("推荐列表已经变化，请刷新后重新确认")
        items = [
            {**candidates[item_id], "status": "confirmed"}
            for item_id in dict.fromkeys(accepted_ids)
        ]
        decisions = {
            **{item_id: "confirmed" for item_id in accepted_ids},
            **{item_id: "rejected" for item_id in rejected_ids},
        }
        return self.db.save_quality_reference_group(
            uuid.uuid4().hex, project_id, profile_id, "confirmed", items, decisions,
        )

    def list_group(self, project_id: str, profile_id: str) -> dict[str, Any]:
        self.projects.get(project_id)
        return self.db.latest_quality_reference_group(project_id, profile_id) or {
            "id": None,
            "project_id": project_id,
            "profile_id": profile_id,
            "version": 0,
            "action": "none",
            "items": [],
            "decisions": {},
            "created_at": None,
        }

    def remove(self, project_id: str, profile_id: str, item_id: str) -> dict[str, Any]:
        current = self.list_group(project_id, profile_id)
        if not any(item["id"] == item_id for item in current["items"]):
            raise LookupError("这条参考已经不在评分参考组中")
        items = [item for item in current["items"] if item["id"] != item_id]
        return self.db.save_quality_reference_group(
            uuid.uuid4().hex, project_id, profile_id, "removed", items,
            {**current["decisions"], item_id: "removed"},
        )

    def history(self, project_id: str, profile_id: str) -> list[dict[str, Any]]:
        self.projects.get(project_id)
        return self.db.list_quality_reference_group_history(project_id, profile_id)

    def _reference_candidates(self, project_id: str) -> list[dict[str, Any]]:
        candidates = []
        for source in self.references.list():
            if source.get("status") != "active":
                continue
            if source.get("project_id") not in {None, project_id}:
                continue
            if (source.get("classification") or {}).get("trust") != "user_confirmed":
                continue
            version = source.get("latest_version")
            if not version:
                continue
            content_type = source.get("content_type")
            role = {
                "popular_sample": "high_quality_anchor",
                "reference_work": "ordinary_anchor",
                "competitor_work": "ordinary_anchor",
            }.get(content_type)
            if role is None:
                continue
            candidates.append({
                "id": f"reference:{source['id']}:{version['id']}",
                "role": role,
                "role_label": ROLE_LABELS[role],
                "source_kind": "reference",
                "source_id": source["id"],
                "version_id": version["id"],
                "title": source["title"],
                "reason": (
                    "你已确认它是爆款样本，可用于观察高质量稿的评分位置。"
                    if role == "high_quality_anchor"
                    else "你已确认这份资料，可用于校准普通稿与优秀稿的差距。"
                ),
                "source_preserved": True,
            })
        by_role: dict[str, list[dict[str, Any]]] = {}
        for item in candidates:
            by_role.setdefault(item["role"], []).append(item)
        return [item for role in ROLE_LABELS for item in by_role.get(role, [])[:2]]

    def _history_candidates(self, project) -> list[dict[str, Any]]:
        candidates = []
        for run in self.db.list_runs(project.id):
            run_path = project.path / "runs" / run["id"]
            checkpoint = reconcile_legacy_checkpoint(run_path)
            if checkpoint:
                candidates.append({
                    "id": f"run:{run['id']}:{checkpoint['manuscript_hash']}",
                    "role": "historical_baseline",
                    "role_label": ROLE_LABELS["historical_baseline"],
                    "source_kind": "run",
                    "source_id": run["id"],
                    "version_id": checkpoint["manuscript_hash"],
                    "title": f"历史最佳稿 {float(checkpoint['score']):g} 分",
                    "reason": "这是本项目已保存的最佳稿，用来观察新评分标准下的变化。",
                    "source_path": checkpoint["manuscript_path"],
                    "source_preserved": True,
                })
                break
        return candidates
