from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import difflib
import hashlib
import json
import re
from pathlib import Path

from novel_flywheel.db import Database
from novel_flywheel.projects import ProjectStore
from novel_flywheel.storage import atomic_write
from novel_flywheel.story_state import StoryStateStore, validate_locked_facts


MAX_OUTLINE_CHARACTERS = 100_000


@dataclass(frozen=True)
class OutlineBlock:
    index: int
    label: str
    text: str


class OutlineService:
    def __init__(self, db: Database, projects: ProjectStore, gateway=None) -> None:
        self.db = db
        self.projects = projects
        self.gateway = gateway
        self.states = StoryStateStore(db)

    def current(self, project_id: str) -> dict:
        project = self.projects.get(project_id)
        state = self.states.ensure(project_id, project.path)
        outline = state.data.get("outline")
        manuscript = project.path / "manuscript" / "story.md"
        manuscript_exists = manuscript.is_file() and bool(manuscript.read_text(encoding="utf-8").strip())
        if isinstance(outline, dict) and str(outline.get("content") or "").strip():
            content = self._clean_content(str(outline["content"]))
            source = str(outline.get("source") or "candidate")
            version = int(outline.get("version") or 1)
            updated_at = outline.get("updated_at")
        else:
            content = self._legacy_outline(project_id, project.path)
            source = "legacy_run" if content else "none"
            version = 0
            updated_at = None
        stage = "manuscript_started" if manuscript_exists else "outline_only" if content else "no_outline"
        return {
            "exists": bool(content), "content": content, "source": source,
            "outline_version": version, "state_revision": state.revision,
            "updated_at": updated_at, "stage": stage,
            "manuscript_exists": manuscript_exists,
            "message": self._stage_message(stage),
        }

    def create_candidate(self, project_id: str, content: str, *, title: str = "候选大纲",
                         metadata: dict | None = None) -> dict:
        project = self.projects.get(project_id)
        content = self._clean_content(content)
        state = self.states.ensure(project_id, project.path)
        created_at = self._now()
        base_metadata = {
            **(metadata or {}), "title": self._clean_title(title), "created_at": created_at,
        }
        candidate = self.states.create_candidate(
            project_id, None, state.revision, "outline", self._hash(content), base_metadata,
        )
        relative = Path("learning") / "candidates" / f"outline-{candidate.id}.md"
        try:
            atomic_write(project.path / relative, content)
            candidate = self.states.update_candidate(
                candidate.id, content_hash=self._hash(content),
                metadata={**base_metadata, "relative_path": relative.as_posix()},
            )
        except Exception:
            self.states.reject(candidate.id, "candidate file write failed")
            raise
        return self._public_candidate(candidate, content)

    def list_candidates(self, project_id: str, *, include_resolved: bool = False) -> list[dict]:
        self.projects.get(project_id)
        status = None if include_resolved else "pending"
        result = []
        for candidate in self.states.list_candidates(project_id, kind="outline", status=status):
            try:
                result.append(self._public_candidate(candidate, self._candidate_content(project_id, candidate)))
            except (OSError, ValueError):
                result.append({
                    "id": candidate.id, "status": candidate.status,
                    "title": candidate.metadata.get("title") or "候选大纲",
                    "created_at": candidate.metadata.get("created_at"),
                    "content": "", "available": False,
                    "message": "候选文件不可用，请放弃后重新生成。",
                })
        return result

    def get_candidate(self, project_id: str, candidate_id: str) -> dict:
        candidate = self._candidate(project_id, candidate_id)
        return self._public_candidate(candidate, self._candidate_content(project_id, candidate))

    def update_candidate(self, project_id: str, candidate_id: str, content: str,
                         *, title: str | None = None) -> dict:
        project = self.projects.get(project_id)
        candidate = self._candidate(project_id, candidate_id)
        content = self._clean_content(content)
        path = self._candidate_path(project.path, candidate)
        old_content = path.read_text(encoding="utf-8") if path.is_file() else None
        atomic_write(path, content)
        metadata = {
            **candidate.metadata,
            "title": self._clean_title(title or candidate.metadata.get("title") or "候选大纲"),
            "updated_at": self._now(),
        }
        try:
            updated = self.states.update_candidate(
                candidate_id, content_hash=self._hash(content), metadata=metadata,
            )
        except Exception:
            if old_content is not None:
                atomic_write(path, old_content)
            raise
        return self._public_candidate(updated, content)

    def reject_candidate(self, project_id: str, candidate_id: str, reason: str = "") -> dict:
        candidate = self._candidate(project_id, candidate_id)
        self.states.reject(candidate.id, reason or "用户放弃候选大纲")
        rejected = self.states.get_candidate(candidate.id)
        assert rejected is not None
        return self._public_candidate(rejected, self._candidate_content(project_id, rejected))

    def compare_candidate(self, project_id: str, candidate_id: str) -> dict:
        current = self.current(project_id)
        candidate = self.get_candidate(project_id, candidate_id)
        changes = self._compare(current["content"], candidate["content"])
        summary = {
            "added": sum(item["type"] == "added" for item in changes),
            "removed": sum(item["type"] == "removed" for item in changes),
            "changed": sum(item["type"] in {"changed", "reordered", "uncertain"} for item in changes),
            "uncertain": sum(item["type"] == "uncertain" for item in changes),
        }
        state = self.states.get(project_id)
        assert state is not None
        lock_failures = validate_locked_facts(current["content"], candidate["content"], state.data)
        risks = []
        if current["manuscript_exists"]:
            risks.append("作品已经有正文；应用后只改变后续创作依据，不会修改现有正文。")
        if summary["removed"]:
            risks.append(f"候选版本删除了 {summary['removed']} 个剧情块，请确认伏笔和结局仍能兑现。")
        if lock_failures:
            risks.append("候选版本遗漏了已锁定设定，当前不能应用。")
        return {
            "project_id": project_id, "candidate_id": candidate_id,
            "state_revision": current["state_revision"], "stage": current["stage"],
            "current": current, "candidate": candidate, "changes": changes,
            "summary": summary, "risks": risks, "lock_failures": lock_failures,
            "can_apply": not lock_failures, "model_called": False,
            "semantic_review_recommended": bool(summary["uncertain"]),
        }

    def apply_candidate(self, project_id: str, candidate_id: str, *,
                        change_ids: list[str] | None = None,
                        expected_revision: int | None = None,
                        allow_full_with_manuscript: bool = False,
                        source: str = "candidate") -> dict:
        project = self.projects.get(project_id)
        candidate = self._candidate(project_id, candidate_id)
        candidate_content = self._candidate_content(project_id, candidate)
        current = self.current(project_id)
        if current["manuscript_exists"] and change_ids is None and not allow_full_with_manuscript:
            raise ValueError("作品已有正文；整体应用前需要再次确认，现有正文不会被修改")
        report = self.compare_candidate(project_id, candidate_id)
        if expected_revision is not None and expected_revision != report["state_revision"]:
            raise ValueError("当前大纲已经变化，请刷新比较结果后再应用")
        if report["lock_failures"]:
            raise ValueError("候选大纲遗漏了锁定设定，不能应用")
        content = (
            candidate_content if change_ids is None
            else self._merge_selected(current["content"], candidate_content, report["changes"], change_ids)
        )
        state = self.states.get(project_id)
        if state is None:
            raise LookupError("StoryState not found")
        lock_failures = validate_locked_facts(current["content"], content, state.data)
        if lock_failures:
            raise ValueError("候选大纲遗漏了锁定设定，不能应用")
        version = current["outline_version"] + 1
        outline = {
            "content": content, "version": version, "source": source,
            "candidate_id": candidate_id, "updated_at": self._now(),
            "content_hash": self._hash(content),
        }
        committed = self.states.commit(
            candidate_id, expected_revision or state.revision,
            {**state.data, "outline": outline},
        )
        atomic_write(project.path / "plot" / "outline.md", content)
        self._mark_outline_artifacts_stale(project.path, project_id)
        return {
            **self.current(project_id), "story_state_revision": committed.revision,
            "formal_manuscript_changed": False,
        }

    def history(self, project_id: str) -> list[dict]:
        self.projects.get(project_id)
        result = []
        for state in self.states.history(project_id):
            outline = state.data.get("outline")
            if not isinstance(outline, dict) or not str(outline.get("content") or "").strip():
                continue
            result.append({
                "outline_version": int(outline.get("version") or 1),
                "story_state_revision": state.revision,
                "source": outline.get("source") or "candidate",
                "updated_at": outline.get("updated_at"),
                "content": self._clean_content(str(outline["content"])),
                "is_current": False,
            })
        if result:
            result[-1]["is_current"] = True
        return result

    def restore(self, project_id: str, *, outline_version: int) -> dict:
        target = next(
            (item for item in self.history(project_id) if item["outline_version"] == outline_version),
            None,
        )
        if target is None:
            raise LookupError("大纲历史版本不存在")
        candidate = self.create_candidate(
            project_id, target["content"], title=f"恢复第 {outline_version} 版",
            metadata={"restores_outline_version": outline_version},
        )
        return self.apply_candidate(
            project_id, candidate["id"], allow_full_with_manuscript=True, source="restored",
        )

    def overview(self, project_id: str) -> dict:
        return {
            "current": self.current(project_id),
            "candidates": self.list_candidates(project_id),
            "history": self.history(project_id),
        }

    async def semantic_review(self, project_id: str, candidate_id: str) -> dict:
        report = self.compare_candidate(project_id, candidate_id)
        uncertain = [item for item in report["changes"] if item["type"] == "uncertain"]
        if not uncertain:
            return report
        if self.gateway is None:
            raise ValueError("规划模型当前不可用，请先检查模型配置")
        state = self.states.get(project_id)
        locked_facts = (state.data.get("locked_facts") if state else []) or []
        evidence = [{
            "id": item["id"], "type": item["type"], "label": item["label"],
            "current_text": item["current_text"][:1_000],
            "candidate_text": item["candidate_text"][:1_000],
        } for item in uncertain[:10]]
        user = json.dumps({
            "changes": evidence,
            "locked_facts": locked_facts[:20],
        }, ensure_ascii=False, indent=2)
        result = await self.gateway.complete(
            "planning",
            "你只判断候选大纲中本地程序无法确定的变化。返回 JSON，不改写大纲。"
            "格式：{\"decisions\":[{\"id\":\"变化ID\",\"type\":\"changed或reordered\","
            "\"explanation\":\"一句易懂说明\",\"impact\":\"会影响哪里\"}]}。",
            user[:30_000], max_output_tokens=2048,
        )
        decisions = self._semantic_decisions(result.text, {item["id"] for item in uncertain})
        by_id = {item["id"]: item for item in decisions}
        changes = []
        for item in report["changes"]:
            decision = by_id.get(item["id"])
            changes.append({**item, **decision} if decision else item)
        report["changes"] = changes
        report["summary"] = {
            "added": sum(item["type"] == "added" for item in changes),
            "removed": sum(item["type"] == "removed" for item in changes),
            "changed": sum(item["type"] in {"changed", "reordered", "uncertain"} for item in changes),
            "uncertain": sum(item["type"] == "uncertain" for item in changes),
        }
        report["model_called"] = True
        report["semantic_review_recommended"] = bool(report["summary"]["uncertain"])
        report["model_receipt"] = result.receipt
        return report

    def _legacy_outline(self, project_id: str, project_path: Path) -> str:
        for run in self.db.list_runs(project_id):
            if run["status"] != "completed":
                continue
            path = project_path / "runs" / run["id"] / "outputs" / "planning.md"
            if path.is_file() and (content := path.read_text(encoding="utf-8")).strip():
                return self._clean_content(content)
        return ""

    def _candidate(self, project_id: str, candidate_id: str):
        self.projects.get(project_id)
        candidate = self.states.get_candidate(candidate_id)
        if candidate is None or candidate.project_id != project_id or candidate.kind != "outline":
            raise LookupError("候选大纲不存在")
        return candidate

    def _candidate_content(self, project_id: str, candidate) -> str:
        project = self.projects.get(project_id)
        path = self._candidate_path(project.path, candidate)
        content = self._clean_content(path.read_text(encoding="utf-8"))
        if self._hash(content) != candidate.content_hash:
            raise ValueError("候选大纲内容与保存记录不一致，请重新生成")
        return content

    @staticmethod
    def _candidate_path(project_path: Path, candidate) -> Path:
        raw = candidate.metadata.get("relative_path")
        if not raw:
            raise ValueError("候选大纲缺少文件记录")
        path = (project_path / raw).resolve()
        if not path.is_relative_to(project_path.resolve()):
            raise ValueError("候选大纲路径无效")
        return path

    @classmethod
    def _compare(cls, current: str, candidate: str) -> list[dict]:
        current_blocks = cls._blocks(current)
        candidate_blocks = cls._blocks(candidate)
        current_by_label = {block.label: block for block in current_blocks}
        candidate_by_label = {block.label: block for block in candidate_blocks}
        changes = []
        matched_current: set[int] = set()
        for block in candidate_blocks:
            existing = current_by_label.get(block.label)
            if existing is None:
                changes.append(cls._change("added", None, block, "候选版本新增了这一段剧情。"))
                continue
            matched_current.add(existing.index)
            ratio = difflib.SequenceMatcher(None, cls._normalize(existing.text), cls._normalize(block.text)).ratio()
            if ratio >= 0.985 and existing.index == block.index:
                continue
            change_type = "uncertain" if ratio < 0.30 else "reordered" if ratio >= 0.985 else "changed"
            explanation = {
                "changed": "同一剧情位置的内容发生了变化。",
                "reordered": "这段剧情在候选版本中的位置发生了变化。",
                "uncertain": "文字和结构变化较大，本地程序无法可靠判断是否仍是同一情节。",
            }[change_type]
            changes.append(cls._change(change_type, existing, block, explanation))
        for block in current_blocks:
            if block.index not in matched_current and block.label not in candidate_by_label:
                changes.append(cls._change("removed", block, None, "候选版本删除了这一段剧情。"))
        return sorted(changes, key=lambda item: (
            item["candidate_index"] if item["candidate_index"] is not None else 10_000 + item["current_index"]
        ))

    @classmethod
    def _merge_selected(cls, current: str, candidate: str, changes: list[dict],
                        selected_ids: list[str]) -> str:
        selected = {item["id"]: item for item in changes if item["id"] in set(selected_ids)}
        if len(selected) != len(set(selected_ids)):
            raise ValueError("选择的变化已经失效，请重新比较")
        blocks = list(cls._blocks(current))
        candidate_blocks = cls._blocks(candidate)
        by_current = {block.index: position for position, block in enumerate(blocks)}
        for item in sorted(selected.values(), key=lambda value: value["current_index"] or 0, reverse=True):
            current_index = item["current_index"]
            candidate_index = item["candidate_index"]
            if item["type"] == "removed" and current_index in by_current:
                blocks.pop(by_current[current_index])
            elif current_index is not None and candidate_index is not None and current_index in by_current:
                blocks[by_current[current_index]] = candidate_blocks[candidate_index]
            by_current = {block.index: position for position, block in enumerate(blocks)}
        additions = [item for item in selected.values() if item["type"] == "added"]
        for item in sorted(additions, key=lambda value: value["candidate_index"]):
            block = candidate_blocks[item["candidate_index"]]
            blocks.insert(min(item["candidate_index"], len(blocks)), block)
        return cls._clean_content("\n\n".join(block.text.strip() for block in blocks))

    @classmethod
    def _blocks(cls, content: str) -> list[OutlineBlock]:
        content = content.strip()
        if not content:
            return []
        lines = content.splitlines()
        chunks: list[list[str]] = []
        current: list[str] = []
        for line in lines:
            if re.match(r"^#{1,4}\s+\S", line) and current:
                chunks.append(current)
                current = [line]
            else:
                current.append(line)
        if current:
            chunks.append(current)
        if len(chunks) == 1 and not re.match(r"^#{1,4}\s+\S", chunks[0][0]):
            paragraphs = [part.strip() for part in re.split(r"\n\s*\n", content) if part.strip()]
            chunks = [part.splitlines() for part in paragraphs]
        result = []
        for index, chunk in enumerate(chunks):
            text = "\n".join(chunk).strip()
            heading = re.match(r"^#{1,4}\s+(.+)$", chunk[0].strip())
            label = heading.group(1).strip() if heading else f"第 {index + 1} 段"
            result.append(OutlineBlock(index, label, text))
        return result

    @classmethod
    def _change(cls, change_type: str, current: OutlineBlock | None,
                candidate: OutlineBlock | None, explanation: str) -> dict:
        identity = "|".join((
            change_type, str(current.index if current else ""),
            str(candidate.index if candidate else ""),
            current.text if current else "", candidate.text if candidate else "",
        ))
        return {
            "id": hashlib.sha1(identity.encode("utf-8")).hexdigest()[:16],
            "type": change_type, "label": (candidate or current).label,
            "current_index": current.index if current else None,
            "candidate_index": candidate.index if candidate else None,
            "current_text": current.text if current else "",
            "candidate_text": candidate.text if candidate else "",
            "explanation": explanation,
        }

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(r"\W+", "", value, flags=re.UNICODE).lower()

    @staticmethod
    def _semantic_decisions(text: str, allowed_ids: set[str]) -> list[dict]:
        value = str(text or "").strip()
        if value.startswith("```"):
            value = re.sub(r"^```(?:json)?\s*|\s*```$", "", value, flags=re.IGNORECASE)
        try:
            payload = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("模型没有返回可读取的判断结果，请重新尝试") from exc
        decisions = payload.get("decisions") if isinstance(payload, dict) else None
        if not isinstance(decisions, list):
            raise ValueError("模型判断结果缺少变化列表，请重新尝试")
        cleaned = []
        for item in decisions:
            if not isinstance(item, dict) or item.get("id") not in allowed_ids:
                continue
            change_type = item.get("type")
            if change_type not in {"changed", "reordered", "uncertain"}:
                continue
            cleaned.append({
                "id": item["id"], "type": change_type,
                "explanation": str(item.get("explanation") or "模型未补充说明")[:500],
                "impact": str(item.get("impact") or "尚未说明具体影响")[:500],
            })
        if not cleaned:
            raise ValueError("模型没有识别出可用的变化判断，请重新尝试")
        return cleaned

    def _mark_outline_artifacts_stale(self, project_path: Path, project_id: str) -> None:
        artifact_types = ("scene_briefs", "short_causal_chain")
        with self.db.connect() as connection:
            rows = connection.execute(
                "SELECT id,artifact_type FROM project_learning_artifacts a "
                "WHERE project_id=? AND status='active' "
                "AND artifact_type IN (?,?) AND version=("
                "SELECT MAX(version) FROM project_learning_artifacts "
                "WHERE project_id=a.project_id AND artifact_type=a.artifact_type)",
                (project_id, *artifact_types),
            ).fetchall()
            for row in rows:
                connection.execute(
                    "UPDATE project_learning_artifacts SET status='stale' WHERE id=?",
                    (row["id"],),
                )
        for row in rows:
            path = project_path / "learning" / f"{row['artifact_type']}.json"
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            value["status"] = "stale"
            atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")

    @staticmethod
    def _hash(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def _clean_title(title: str) -> str:
        value = str(title or "").strip()
        if not value or len(value) > 80:
            raise ValueError("候选大纲标题需要 1-80 个字符")
        return value

    @staticmethod
    def _clean_content(content: str) -> str:
        value = str(content or "").strip()
        if not value:
            raise ValueError("候选大纲不能为空")
        if len(value) > MAX_OUTLINE_CHARACTERS:
            raise ValueError("候选大纲不能超过 100,000 个字符")
        return value + "\n"

    @staticmethod
    def _public_candidate(candidate, content: str) -> dict:
        return {
            "id": candidate.id, "status": candidate.status,
            "title": candidate.metadata.get("title") or "候选大纲",
            "created_at": candidate.metadata.get("created_at"),
            "updated_at": candidate.metadata.get("updated_at"),
            "content": content, "available": True,
            "base_revision": candidate.base_revision,
            "message": "等待你查看和比较" if candidate.status == "pending" else "候选已处理",
        }

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _stage_message(stage: str) -> str:
        return {
            "no_outline": "当前还没有正式大纲，可以把候选版本设为初始大纲。",
            "outline_only": "当前已有大纲但尚无正文，可以整体应用或逐项选择变化。",
            "manuscript_started": "当前已有正文；应用大纲只影响后续创作，不会修改现有正文。",
        }[stage]
