import hashlib
from types import SimpleNamespace

from novel_flywheel.quality_summary import (
    build_quality_summary,
    effective_han_characters,
    merge_quality_issues,
)


def test_effective_han_count_excludes_headings_markers_whitespace_and_punctuation() -> None:
    text = (
        "# 内部标题\n\n"
        "你好，世界！\n\n"
        "<!-- NOVEL_FLYWHEEL_SEGMENT -->\n\n"
        "她回来了。OpenAI 2026"
    )

    assert effective_han_characters(text) == 8


def test_duplicate_window_issues_merge_into_one_issue_with_multiple_evidence() -> None:
    report = {
        "final_attempts": [{
            "attempt": 1,
            "review": {"issues": [
                {
                    "category": "story",
                    "severity": "high",
                    "status": "unresolved",
                    "location": "会面准备场景",
                    "evidence": "许棠没有决定是否会面。",
                    "action": "补足许棠的自主决定。",
                },
                {
                    "category": "story",
                    "severity": "medium",
                    "status": "partially_resolved",
                    "location": "材料披露场景",
                    "evidence": "披露范围仍由林照决定。",
                    "action": "补足许棠的自主决定。",
                },
            ]},
        }],
    }

    issues = merge_quality_issues(report)

    assert len(issues) == 1
    assert issues[0]["title"] == "人物与情节逻辑"
    assert issues[0]["status"] == "unresolved"
    assert issues[0]["severity"] == "high"
    assert issues[0]["repair_mode"] == "structural"
    assert issues[0]["handling_label"] == "规划模型定位，精修模型修改"
    assert issues[0]["source_label"] == "终审发现"
    assert [item["location"] for item in issues[0]["evidence"]] == [
        "会面准备场景", "材料披露场景",
    ]


def test_quality_summary_explains_state_count_comparison_and_next_action() -> None:
    text = "正文" * 4600
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    project = SimpleNamespace(
        mode="short",
        metadata={
            "platform_profile_id": "zhihu-salt-short",
            "target_words": 10_000,
        },
    )
    report = {
        "status": "failed",
        "best_score": 58.35,
        "terminal_reviewed_hash": digest,
        "final_attempts": [{
            "attempt": 1,
            "review": {
                "score": 58.35,
                "dimensions": {"commercial": 60, "story": 55, "prose": 60},
                "issues": [{
                    "category": "story", "severity": "high",
                    "status": "unresolved", "evidence": "人物没有作出决定。",
                    "action": "补足人物选择。",
                }],
            },
        }],
    }
    checkpoint = {
        "score": 64.75,
        "manuscript_hash": digest,
        "scoring_profile_id": "legacy-v1",
        "judge_signature": "legacy-unknown",
        "outcome": "legacy_protected",
    }

    summary = build_quality_summary(project, "run-1", text, report, checkpoint)

    assert summary["manuscript_state"]["protected_best"] is True
    assert summary["score"]["best"] == 64.75
    assert summary["score"]["comparable"] is False
    assert summary["profile"]["judge_signature"] == "legacy-unknown"
    assert summary["profile"]["judge_label"] == "旧记录未保存模型名称"
    assert summary["word_count"] == {
        "label": "有效正文汉字",
        "current": 9200,
        "minimum": 9000,
        "maximum": 11000,
        "remaining": 0,
        "within_target": True,
    }
    assert summary["publication_authority"]["can_set_formal"] is False
    assert "终审" in "".join(summary["publication_authority"]["blocking_reasons"])
    assert summary["next_action"] == "继续修改候选稿"


def test_quality_summary_uses_review_bound_to_protected_manuscript() -> None:
    text = "正文" * 4500
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    project = SimpleNamespace(
        mode="short",
        metadata={
            "platform_profile_id": "zhihu-salt-short", "target_words": 10_000,
        },
    )
    protected_review = {
        "score": 84, "scoring_profile_id": "zhihu-short-v2",
        "judge_signature": "provider/model",
        "dimensions": {"commercial": 85, "story": 84, "prose": 82},
        "issues": [],
    }
    report = {
        "status": "passed", "terminal_reviewed_hash": digest,
        "final_attempts": [{"attempt": 2, "review": {
            "score": 76, "scoring_profile_id": "zhihu-short-v2",
            "judge_signature": "provider/model",
            "dimensions": {"commercial": 76, "story": 76, "prose": 76},
            "issues": [{
                "category": "story", "severity": "high", "status": "unresolved",
                "action": "较差稿的问题",
            }],
        }}],
    }
    checkpoint = {
        "manuscript_hash": digest, "score": 84,
        "scoring_profile_id": "zhihu-short-v2",
        "judge_signature": "provider/model", "review": protected_review,
    }

    summary = build_quality_summary(project, "run", text, report, checkpoint)

    assert summary["score"]["current"] == 84
    assert summary["score"]["dimensions"] == protected_review["dimensions"]
    assert summary["profile"]["judge_label"] == "provider/model"
    assert summary["issues"] == []


def test_quality_summary_labels_missing_legacy_judge_in_plain_chinese() -> None:
    text = "正文"
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    project = SimpleNamespace(mode="short", metadata={})

    summary = build_quality_summary(
        project,
        "run",
        text,
        {
            "terminal_reviewed_hash": "another-manuscript",
            "final_attempts": [{"review": {
                "judge_signature": "new-provider/new-model",
            }}],
        },
        {"manuscript_hash": digest},
    )

    assert summary["profile"]["judge_signature"] == "legacy-unknown"
    assert summary["profile"]["judge_label"] == "旧记录未保存模型名称"


def test_quality_issue_summary_labels_all_new_states_in_plain_chinese() -> None:
    statuses = {
        "resolved": "已解决",
        "partially_resolved": "部分解决",
        "unresolved": "未解决",
        "uncertain": "待确认",
        "preserved": "保留原写法",
    }
    report = {"final_attempts": [{"review": {"issues": [
        {
            "issue_id": f"issue-{status}", "category": "style",
            "severity": "low", "status": status, "action": status,
        }
        for status in statuses
    ]}}]}

    issues = merge_quality_issues(report)

    assert {item["status"]: item["status_label"] for item in issues} == statuses


def test_preserved_advisory_is_not_counted_as_waiting_for_action() -> None:
    project = SimpleNamespace(mode="short", metadata={})
    report = {"final_attempts": [{"review": {"issues": [{
        "issue_id": "style-1", "category": "style", "severity": "high",
        "status": "preserved", "action": "Keep the original wording",
    }]}}]}

    summary = build_quality_summary(project, "run", "", report, None)

    assert summary["issue_counts"] == {"total": 1, "mandatory": 0, "unresolved": 0}
