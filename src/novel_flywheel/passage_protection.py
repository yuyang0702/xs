from __future__ import annotations

import hashlib
import re
import uuid
from typing import Any


MODE_LABELS = {
    "soft": "尽量不改文字",
    "exact": "一个字也不改",
}
STATUS_LABELS = {
    "active": "保护中",
    "allow_next_change": "下次修改可变动一次",
    "inactive": "已取消保护",
    "changed_once": "已使用一次修改，请重新选择要保护的文字",
}


class PassageProtectionService:
    def __init__(self, db) -> None:
        self.db = db

    def create(
        self, project_id: str, manuscript: str, *, excerpt: str,
        mode: str, label: str = "保护片段",
    ) -> dict[str, Any]:
        if mode not in MODE_LABELS:
            raise ValueError("保护方式只能选择“尽量不改文字”或“一个字也不改”")
        selected = excerpt.strip()
        paragraphs = _paragraphs(manuscript)
        chosen = _paragraphs(selected)
        if not chosen or selected != "\n\n".join(chosen):
            raise ValueError("请选择一个或多个完整段落")
        matches = [
            index for index in range(len(paragraphs) - len(chosen) + 1)
            if paragraphs[index:index + len(chosen)] == chosen
        ]
        if not matches:
            raise ValueError("请选择候选稿中的完整段落，不能只选半段")
        protection_id = uuid.uuid4().hex
        start = matches[0]
        value = {
            "id": protection_id,
            "kind": "passage",
            "label": label.strip()[:80] or "保护片段",
            "mode": mode,
            "excerpt": selected,
            "normalized_excerpt": _soft_normalize(selected),
            "paragraph_start": start + 1,
            "paragraph_end": start + len(chosen),
            "source_hash": hashlib.sha256(manuscript.encode("utf-8")).hexdigest(),
            "active": True,
            "allow_next_change": False,
            "status": "active",
        }
        self.db.save_lock(
            project_id, f"passage.{protection_id}", value, "user.passage_protection",
        )
        return self._public(value)

    def list(self, project_id: str) -> list[dict[str, Any]]:
        return [
            self._public(item["value"])
            for item in self.db.list_locks(project_id)
            if item["key"].startswith("passage.")
            and isinstance(item.get("value"), dict)
        ]

    def remove(self, project_id: str, protection_id: str) -> dict[str, Any]:
        key, value = self._find(project_id, protection_id)
        updated = {
            **value, "active": False, "allow_next_change": False,
            "status": "inactive",
        }
        self.db.save_lock(project_id, key, updated, "user.passage_protection_removed")
        return self._public(updated)

    def allow_next_change(self, project_id: str, protection_id: str) -> dict[str, Any]:
        key, value = self._find(project_id, protection_id)
        if not value.get("active"):
            raise ValueError("这段文字已经取消保护")
        updated = {**value, "allow_next_change": True, "status": "allow_next_change"}
        self.db.save_lock(project_id, key, updated, "user.passage_change_allowed")
        return self._public(updated)

    def consume_allowed_changes(
        self, project_id: str, consumed: list[dict[str, Any]],
    ) -> None:
        for item in consumed:
            try:
                key, value = self._find(project_id, item["id"])
            except LookupError:
                continue
            if not value.get("allow_next_change"):
                continue
            updated = {
                **value, "active": False, "allow_next_change": False,
                "status": "changed_once",
            }
            self.db.save_lock(project_id, key, updated, "runtime.passage_change_consumed")

    def _find(self, project_id: str, protection_id: str) -> tuple[str, dict[str, Any]]:
        for item in self.db.list_locks(project_id):
            value = item.get("value")
            if (item["key"] == f"passage.{protection_id}"
                    and isinstance(value, dict)):
                return item["key"], value
        raise LookupError("找不到这条保护片段")

    @staticmethod
    def _public(value: dict[str, Any]) -> dict[str, Any]:
        return {
            **value,
            "mode_label": MODE_LABELS.get(value.get("mode"), "未知方式"),
            "status_label": STATUS_LABELS.get(value.get("status"), "状态未知"),
        }


def applicable_passage_locks(locks: list[dict], source: str) -> list[dict]:
    result = []
    normalized_source = _soft_normalize(source)
    for item in locks:
        value = item.get("value")
        if (not item.get("key", "").startswith("passage.")
                or not isinstance(value, dict) or not value.get("active")):
            continue
        excerpt = str(value.get("excerpt") or "")
        if excerpt in source or (
            value.get("mode") == "soft"
            and str(value.get("normalized_excerpt") or "") in normalized_source
        ):
            result.append({**value, "lock_key": item["key"]})
    return result


def validate_passage_protections(
    source: str, candidate: str, locks: list[dict],
) -> dict[str, list[dict[str, Any]]]:
    conflicts = []
    consumed = []
    normalized_candidate = _soft_normalize(candidate)
    for lock in locks:
        excerpt = str(lock.get("excerpt") or "")
        unchanged = (
            excerpt in candidate if lock.get("mode") == "exact"
            else str(lock.get("normalized_excerpt") or _soft_normalize(excerpt))
            in normalized_candidate
        )
        if unchanged:
            continue
        item = {
            "id": str(lock.get("id")),
            "label": str(lock.get("label") or "保护片段"),
            "mode": str(lock.get("mode") or "soft"),
        }
        if lock.get("allow_next_change"):
            consumed.append(item)
        else:
            conflicts.append({
                **item,
                "message": f"“{item['label']}”被修改，已保留原文",
            })
    return {"conflicts": conflicts, "consumed": consumed}


def validate_candidate_protections(candidate: str, locks: list[dict]) -> dict[str, Any]:
    results = []
    conflicts = []
    allowed = []
    normalized_candidate = _soft_normalize(candidate)
    candidate_paragraphs = _paragraphs(candidate)
    for envelope in locks:
        value = envelope.get("value")
        if (not envelope.get("key", "").startswith("passage.")
                or not isinstance(value, dict) or not value.get("active")):
            continue
        excerpt = str(value.get("excerpt") or "")
        normalized_excerpt = str(value.get("normalized_excerpt") or "")
        invalid_reason = None
        if not excerpt:
            invalid_reason = "empty_excerpt"
        elif not normalized_excerpt:
            invalid_reason = "empty_normalized_excerpt"
        exact_matches = candidate.count(excerpt) if excerpt else 0
        soft_matches = (
            normalized_candidate.count(normalized_excerpt)
            if normalized_excerpt else 0
        )
        if invalid_reason:
            status = "missing"
        elif value.get("mode") == "exact" and exact_matches:
            status = "unchanged" if exact_matches == 1 else "ambiguous"
        elif soft_matches:
            if soft_matches > 1:
                status = "ambiguous"
            else:
                status = "unchanged" if value.get("mode") == "soft" else "mutated"
        else:
            paragraph_end = value.get("paragraph_end")
            status = (
                "missing"
                if not isinstance(paragraph_end, int) or paragraph_end > len(candidate_paragraphs)
                else "mutated"
            )
        item = {
            "id": str(value.get("id") or envelope["key"].removeprefix("passage.")),
            "label": str(value.get("label") or "保护片段"),
            "mode": str(value.get("mode") or "soft"),
            "status": status,
        }
        if invalid_reason:
            item["reason"] = invalid_reason
        results.append(item)
        if (not invalid_reason and status in {"missing", "mutated"}
                and value.get("allow_next_change")):
            allowed.append(item)
        elif status != "unchanged":
            conflicts.append(item)
    return {
        "passed": not conflicts,
        "conflicts": conflicts,
        "allowed": allowed,
        "results": results,
    }


def passage_prompt_context(locks: list[dict]) -> str:
    if not locks:
        return ""
    lines = ["\n\n受保护片段（必须遵守）："]
    for lock in locks:
        instruction = (
            "原文必须逐字保留"
            if lock.get("mode") == "exact"
            else "保留原有文字，只能调整标点、空格或机械连接"
        )
        if lock.get("allow_next_change"):
            instruction = "用户允许本轮修改一次"
        lines.append(f"- {lock.get('label') or '保护片段'}：{instruction}\n{lock.get('excerpt')}" )
    return "\n".join(lines)


def _paragraphs(text: str) -> list[str]:
    return [item.strip() for item in re.split(r"\n\s*\n", text.strip()) if item.strip()]


def _soft_normalize(text: str) -> str:
    return re.sub(r"[^\w\u3400-\u9fff]+", "", text, flags=re.UNICODE).lower()
