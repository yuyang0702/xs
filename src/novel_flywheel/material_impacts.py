from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from novel_flywheel.generated_artifacts import GeneratedArtifactGateway
from novel_flywheel.storage import atomic_write


class MaterialImpactService:
    def __init__(self, gateway) -> None:
        self.gateway = gateway

    @staticmethod
    def content_hash(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def _root(project_path: Path) -> Path:
        return project_path / ".novel-flywheel" / "material-impacts"

    def record(
        self, project_id: str, project_path: Path, source_path: str,
        before: str, after: str, *, retire_removed_settings: bool,
    ) -> dict[str, Any] | None:
        if not retire_removed_settings or not source_path.startswith("characters/") or before == after:
            return None
        removed = self._meaningful_lines(before) - self._meaningful_lines(after)
        added = self._meaningful_lines(after) - self._meaningful_lines(before)
        if not removed and not added:
            return None
        impact = {
            "id": uuid.uuid4().hex,
            "project_id": project_id,
            "source_path": source_path,
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "summary": "",
            "removed_lines": sorted(removed),
            "added_lines": sorted(added),
            "before": before,
            "after": after,
            "proposals": [],
            "error": None,
        }
        self.save(project_path, impact)
        return self.public(impact)

    @staticmethod
    def _meaningful_lines(content: str) -> set[str]:
        return {
            line.strip().lstrip("-* ").strip()
            for line in content.splitlines()
            if line.strip() and not line.strip().startswith(("#", "---"))
            and not re.match(r"^(name|role|age|status|arc|tags):", line.strip())
        }

    def save(self, project_path: Path, impact: dict[str, Any]) -> None:
        path = self._root(project_path) / f"{impact['id']}.json"
        atomic_write(path, json.dumps(impact, ensure_ascii=False, indent=2) + "\n")

    def get(self, project_path: Path, impact_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"[0-9a-f]{32}", impact_id):
            raise LookupError("material_impact_not_found")
        path = self._root(project_path) / f"{impact_id}.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LookupError("material_impact_not_found") from exc

    def list(self, project_path: Path) -> list[dict[str, Any]]:
        impacts = []
        for path in self._root(project_path).glob("*.json"):
            try:
                impact = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if impact.get("status") not in {"applied", "dismissed"}:
                impacts.append(self.public(impact))
        return sorted(impacts, key=lambda item: item.get("created_at", ""), reverse=True)

    @staticmethod
    def public(impact: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in impact.items() if key not in {"before", "after"}}

    async def analyze(
        self, project_path: Path, impact_id: str, documents: list[dict[str, str]],
    ) -> dict[str, Any]:
        impact = self.get(project_path, impact_id)
        if impact["status"] not in {"pending", "analyzing", "failed"}:
            return self.public(impact)
        by_path = {}
        for document in documents:
            path = document.get("path", "").replace("\\", "/").strip("/")
            content = document.get("content", "")
            if not path or path == impact["source_path"] or len(content) > 80_000:
                continue
            by_path[path] = content
        changed = "\n".join(impact.get("removed_lines", []) + impact.get("added_lines", []))
        ranked = sorted(
            by_path.items(), key=lambda item: self._document_score(changed, item[1]), reverse=True,
        )
        references = []
        reference_size = 0
        for path, content in ranked:
            entry = f"FILE {path}\n{content}"
            if reference_size + len(entry) > 100_000:
                continue
            references.append(entry)
            reference_size += len(entry)
        impact["status"] = "analyzing"
        impact["error"] = None
        self.save(project_path, impact)
        prompt = (
            "Analyze how a confirmed character-setting change affects project material files. "
            "Do not modify manuscript prose. Return JSON only with summary and proposals. Each proposal "
            "must contain path, reason, old_text, and new_text. old_text must be an exact contiguous excerpt "
            "from the supplied file; new_text must preserve the original plot function while honoring the new "
            "character setting. Report no proposal when the relation is speculative.\n\n"
            f"SOURCE FILE: {impact['source_path']}\nBEFORE:\n{impact['before']}\n\nAFTER:\n"
            f"{impact['after']}\n\nRELATED PROJECT MATERIALS:\n" + "\n\n".join(references)
        )
        try:
            result = await self.gateway.complete(
                "maintenance",
                "You maintain internal consistency across a novel project's structured materials.",
                prompt[:120_000], max_output_tokens=4096,
            )
            value = self._json_object(result.text)
            proposals = []
            for raw in value.get("proposals", []):
                if not isinstance(raw, dict):
                    continue
                path = str(raw.get("path", "")).replace("\\", "/").strip("/")
                old = str(raw.get("old_text", ""))
                new = str(raw.get("new_text", ""))
                if path not in by_path or not old or old not in by_path[path] or not new or new == old:
                    continue
                proposals.append({
                    "id": uuid.uuid4().hex, "path": path,
                    "reason": str(raw.get("reason", "")), "old_text": old, "new_text": new,
                    "target_hash": self.content_hash(by_path[path]),
                })
            impact["summary"] = str(value.get("summary", ""))
            impact["proposals"] = proposals
            impact["status"] = "ready" if proposals else "no_impact"
        except Exception as exc:
            impact["status"] = "failed"
            impact["error"] = str(exc)[:500]
        self.save(project_path, impact)
        return self.public(impact)

    @staticmethod
    def _document_score(changed: str, content: str) -> int:
        latin = re.findall(r"[A-Za-z0-9_]{3,}", changed.lower())
        han_runs = re.findall(r"[\u3400-\u9fff]{2,}", changed)
        terms = latin + [run[index:index + 2] for run in han_runs for index in range(len(run) - 1)]
        lowered = content.lower()
        return sum(lowered.count(term.lower()) for term in set(terms))

    @staticmethod
    def _json_object(text: str) -> dict[str, Any]:
        try:
            return GeneratedArtifactGateway().convert_object(
                text, contract_name="material_audit",
            ).payload
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError("material_impact_invalid_json") from exc

    def prepare_apply(
        self, project_path: Path, impact_id: str, proposal_ids: list[str],
    ) -> tuple[dict[str, Any], dict[Path, str]]:
        impact = self.get(project_path, impact_id)
        if impact.get("status") != "ready":
            raise ValueError("material_impact_not_ready")
        selected = [item for item in impact.get("proposals", []) if item.get("id") in proposal_ids]
        if not selected:
            raise ValueError("material_impact_empty_selection")
        updates: dict[Path, str] = {}
        for proposal in selected:
            path = (project_path / proposal["path"]).resolve()
            if not path.is_relative_to(project_path.resolve()) or not path.is_file():
                raise ValueError("material_path_invalid")
            current = updates.get(path, path.read_text(encoding="utf-8"))
            original = path.read_text(encoding="utf-8")
            if self.content_hash(original) != proposal["target_hash"]:
                raise ValueError("material_stale")
            if proposal["old_text"] not in current:
                raise ValueError("material_patch_stale")
            updates[path] = current.replace(proposal["old_text"], proposal["new_text"], 1)
        return impact, updates

    def resolve(self, project_path: Path, impact_id: str, status: str) -> dict[str, Any]:
        if status not in {"applied", "dismissed"}:
            raise ValueError("invalid_material_impact_status")
        impact = self.get(project_path, impact_id)
        impact["status"] = status
        impact["resolved_at"] = datetime.now(timezone.utc).isoformat()
        self.save(project_path, impact)
        return self.public(impact)
