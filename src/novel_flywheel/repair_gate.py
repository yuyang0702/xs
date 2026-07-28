from __future__ import annotations

import hashlib
from typing import Any

from novel_flywheel.passage_protection import validate_candidate_protections
from novel_flywheel.quality_summary import effective_han_characters
from novel_flywheel.story_state import (
    authoritative_fact_snapshot,
    validate_locked_facts,
)


def _check(code: str, passed: bool, message: str) -> dict[str, Any]:
    return {"code": code, "passed": passed, "message": message}


def _literal_checks(candidate: str, contract: dict) -> list[dict[str, Any]]:
    checks = []
    for value in contract.get("required_text", []):
        if isinstance(value, str) and value:
            checks.append(_check(
                "required_text_missing", value in candidate,
                f"候选稿必须保留指定文字：{value}",
            ))
    for value in contract.get("forbidden_text", []):
        if isinstance(value, str) and value:
            checks.append(_check(
                "forbidden_text_remains", value not in candidate,
                f"候选稿必须删除指定文字：{value}",
            ))
    return checks


def _patch_group_checks(
    source: str, candidate: str, patch_results: list[dict],
) -> list[dict[str, Any]]:
    complete = True
    evidence_valid = True
    replayed = source
    for result in patch_results:
        if (not isinstance(result, dict)
                or result.get("accepted") is not True
                or result.get("failures") != []
                or not isinstance(result.get("text"), str)
                or not isinstance(result.get("diffs"), list)
                or not result["diffs"]):
            complete = False
            evidence_valid = False
            continue
        group_text = replayed
        for diff in result["diffs"]:
            if not isinstance(diff, dict):
                complete = False
                evidence_valid = False
                break
            start = diff.get("start")
            old_text = diff.get("old_text")
            new_text = diff.get("new_text")
            if (not isinstance(start, int) or start < 0
                    or not isinstance(old_text, str) or not old_text
                    or not isinstance(new_text, str)
                    or group_text[start:start + len(old_text)] != old_text):
                complete = False
                evidence_valid = False
                break
            group_text = (
                group_text[:start] + new_text + group_text[start + len(old_text):]
            )
        if not evidence_valid or group_text != result["text"]:
            complete = False
            evidence_valid = False
            continue
        replayed = group_text
    external_diff_absent = evidence_valid and replayed == candidate
    return [
        _check(
            "patch_groups_complete", complete,
            "所有修改组均已原子完成，且补丁证据完整。",
        ),
        _check(
            "plan_external_diff_absent", external_diff_absent,
            "来源正文按补丁证据回放后与候选稿完全一致。",
        ),
    ]


def _story_state_checks(
    source: str, candidate: str, story_state: dict,
) -> list[dict[str, Any]]:
    snapshot = authoritative_fact_snapshot(story_state)
    failures = validate_locked_facts(source, candidate, snapshot)
    failure_keys = [
        failure.removeprefix("locked fact removed: ") for failure in failures
    ]
    message = (
        "候选稿保留了当前正文中的全部锁定事实。"
        if not failures else "候选稿删除了锁定事实：" + "、".join(failure_keys)
    )
    return [_check("locked_facts_preserved", not failures, message)]


def _protection_checks(candidate: str, passage_locks: list[dict]) -> list[dict[str, Any]]:
    validation = validate_candidate_protections(candidate, passage_locks)
    allowed = {
        (item["id"], item["status"]) for item in validation["allowed"]
    }
    status_labels = {
        "missing": "缺失",
        "mutated": "被改动",
        "ambiguous": "出现多处，无法唯一定位",
    }
    checks = []
    for item in validation["results"]:
        identity = (item["id"], item["status"])
        label = item["label"]
        if identity in allowed:
            checks.append(_check(
                "passage_protection_change_allowed", True,
                f"保护片段“{label}”本次允许变更，许可尚未消费。",
            ))
        elif item["status"] == "unchanged":
            checks.append(_check(
                "passage_protection_unchanged", True,
                f"保护片段“{label}”保持不变。",
            ))
        else:
            status_label = status_labels.get(item["status"], "无法验证")
            checks.append(_check(
                f"passage_protection_{item['status']}", False,
                f"保护片段“{label}”{status_label}，需要处理后再评审。",
            ))
    return checks


def _length_and_prose_checks(
    candidate: str, analysis: dict, minimum_han: int, maximum_han: int,
) -> list[dict[str, Any]]:
    prose = analysis.get("prose")
    blocking_count = prose.get("blocking_count") if isinstance(prose, dict) else None
    blocking_label = "缺失" if blocking_count is None else str(blocking_count)
    han_count = effective_han_characters(candidate)
    return [
        _check(
            "analysis_coverage_complete", analysis.get("coverage") == 1.0,
            "本地分析已完整覆盖候选稿。",
        ),
        _check(
            "local_prose_blockers_clear", blocking_count == 0,
            f"候选稿本地文风阻断项为 {blocking_label}，必须为 0。",
        ),
        _check(
            "minimum_han_met", han_count >= minimum_han,
            f"候选稿有效汉字数为 {han_count}，下限为 {minimum_han}。",
        ),
        _check(
            "maximum_han_not_exceeded", han_count <= maximum_han,
            f"候选稿有效汉字数为 {han_count}，上限为 {maximum_han}。",
        ),
    ]


def evaluate_candidate_gate(
    *, source: str, candidate: str, source_hash: str,
    analysis: dict, contract: dict, patch_results: list[dict],
    story_state: dict, passage_locks: list[dict],
    minimum_han: int, maximum_han: int,
) -> dict[str, Any]:
    checks = [
        _check(
            "source_hash_matches",
            hashlib.sha256(source.encode("utf-8")).hexdigest() == source_hash,
            "修改来源仍与本轮开始时的正文一致。",
        ),
        _check(
            "analysis_hash_matches",
            analysis.get("text_hash")
            == hashlib.sha256(candidate.encode("utf-8")).hexdigest(),
            "本地分析对应当前候选稿。",
        ),
    ]
    checks.extend(_literal_checks(candidate, contract))
    checks.extend(_patch_group_checks(source, candidate, patch_results))
    checks.extend(_story_state_checks(source, candidate, story_state))
    checks.extend(_protection_checks(candidate, passage_locks))
    checks.extend(_length_and_prose_checks(
        candidate, analysis, minimum_han, maximum_han,
    ))
    blocking = [item for item in checks if not item["passed"]]
    return {
        "passed": not blocking,
        "blocking": blocking,
        "checks": checks,
        "review_mode_hint": "blocked" if blocking else "incremental_candidate",
    }
