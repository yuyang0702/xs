from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from novel_flywheel.contract_runtime import execute_contract_runtime
from novel_flywheel.storage import atomic_write
from novel_flywheel.structured_artifacts import StructuredArtifactContract


class MaterialImpactProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1)
    reason: str = ""
    old_text: str = Field(min_length=1)
    new_text: str = Field(min_length=1)


class MaterialImpactOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = ""
    proposals: list[MaterialImpactProposal] = Field(default_factory=list)


MATERIAL_IMPACT_STRUCTURED_CONTRACT = StructuredArtifactContract(
    name="material_impact_output",
    version=1,
    schema=MaterialImpactOutput.model_json_schema(),
    runtime_authority={"document_paths": "runtime_owned"},
)


class MaterialImpactService:
    def __init__(self, gateway) -> None:
        self.gateway = gateway

    @staticmethod
    def content_hash(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def _root(project_path: Path) -> Path:
        return project_path / ".novel-flywheel" / "material-impacts"

    def impact_path(self, project_path: Path, impact_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", impact_id):
            raise LookupError("material_impact_not_found")
        return self._root(project_path) / f"{impact_id}.json"

    def record(
        self, project_id: str, project_path: Path, source_path: str,
        before: str, after: str, *, retire_removed_settings: bool,
    ) -> dict[str, Any] | None:
        impact = self.prepare_record(
            project_id, source_path, before, after,
            retire_removed_settings=retire_removed_settings,
        )
        if impact is None:
            return None
        self.save(project_path, impact)
        return self.public(impact)

    def prepare_record(
        self, project_id: str, source_path: str,
        before: str, after: str, *, retire_removed_settings: bool,
    ) -> dict[str, Any] | None:
        """Build the exact impact artifact without mutating project authority."""

        if not retire_removed_settings or not source_path.startswith("characters/") or before == after:
            return None
        removed = self._meaningful_lines(before) - self._meaningful_lines(after)
        added = self._meaningful_lines(after) - self._meaningful_lines(before)
        if not removed and not added:
            return None
        return {
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
        path = self.impact_path(project_path, impact_id)
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
        reference_packets: list[list[tuple[str, str]]] = []
        current_packet: list[tuple[str, str]] = []
        current_size = 0
        for path, content in ranked:
            entry_size = len(path) + len(content) + len("FILE \n")
            if current_packet and current_size + entry_size > 80_000:
                reference_packets.append(current_packet)
                current_packet = []
                current_size = 0
            current_packet.append((path, content))
            current_size += entry_size
        if current_packet or not reference_packets:
            reference_packets.append(current_packet)
        impact["status"] = "analyzing"
        impact["error"] = None
        self.save(project_path, impact)
        prompt_prefix = (
            "Analyze how a confirmed character-setting change affects project material files. "
            "Do not modify manuscript prose. Return JSON only with summary and proposals. Each proposal "
            "must contain path, reason, old_text, and new_text. old_text must be an exact contiguous excerpt "
            "from the supplied file; new_text must preserve the original plot function while honoring the new "
            "character setting. Report no proposal when the relation is speculative.\n\n"
            f"SOURCE FILE: {impact['source_path']}\nBEFORE:\n{impact['before']}\n\nAFTER:\n"
            f"{impact['after']}\n\nRELATED PROJECT MATERIALS:\n"
        )
        try:
            values: list[tuple[dict[str, Any], set[str]]] = []
            for packet in reference_packets:
                references = [
                    f"FILE {path}\n{content}" for path, content in packet
                ]
                runtime = await execute_contract_runtime(
                    self.gateway,
                    role="maintenance",
                    system=(
                        "You maintain internal consistency across a novel project's "
                        "structured materials."
                    ),
                    user=prompt_prefix + "\n\n".join(references),
                    contract_name="material_impact_analysis",
                    structured_contract=MATERIAL_IMPACT_STRUCTURED_CONTRACT,
                    semantic_normalizer=lambda value: (
                        MaterialImpactOutput.model_validate(value).model_dump(mode="json")
                    ),
                    domain_validator=lambda payload: MaterialImpactOutput.model_validate(
                        payload,
                    ),
                    max_output_tokens=4096,
                )
                values.append((runtime.payload, {path for path, _ in packet}))
            proposals = []
            seen_proposals: set[tuple[str, str, str]] = set()
            for value, packet_paths in values:
                for raw in value.get("proposals", []):
                    if not isinstance(raw, dict):
                        continue
                    path = str(raw.get("path", "")).replace("\\", "/").strip("/")
                    old = str(raw.get("old_text", ""))
                    new = str(raw.get("new_text", ""))
                    identity = (path, old, new)
                    if (
                        path not in packet_paths or path not in by_path
                        or not old or old not in by_path[path]
                        or not new or new == old or identity in seen_proposals
                    ):
                        continue
                    seen_proposals.add(identity)
                    proposals.append({
                        "id": uuid.uuid4().hex, "path": path,
                        "reason": str(raw.get("reason", "")),
                        "old_text": old, "new_text": new,
                        "target_hash": self.content_hash(by_path[path]),
                    })
            summaries = [
                str(value.get("summary") or "").strip()
                for value, _ in values
                if str(value.get("summary") or "").strip()
            ]
            impact["summary"] = "\n".join(dict.fromkeys(summaries))
            impact["proposals"] = proposals
            impact["status"] = "ready" if proposals else "no_impact"
        except Exception as exc:
            impact["status"] = "failed"
            impact["error"] = (
                "material_impact_analysis_failed:"
                + hashlib.sha256(
                    f"{type(exc).__name__}:{exc}".encode(
                        "utf-8", errors="replace",
                    ),
                ).hexdigest()[:20]
            )
        self.save(project_path, impact)
        return self.public(impact)

    @staticmethod
    def _document_score(changed: str, content: str) -> int:
        latin = re.findall(r"[A-Za-z0-9_]{3,}", changed.lower())
        han_runs = re.findall(r"[\u3400-\u9fff]{2,}", changed)
        terms = latin + [run[index:index + 2] for run in han_runs for index in range(len(run) - 1)]
        lowered = content.lower()
        return sum(lowered.count(term.lower()) for term in set(terms))

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
