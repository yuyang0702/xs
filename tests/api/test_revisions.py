import hashlib
import json
import threading
import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from novel_flywheel.app import create_app
from novel_flywheel.db import Database
from novel_flywheel.manuscript_analysis import analyze_manuscript
from novel_flywheel.models import ModelResult
from novel_flywheel.projects import ProjectCreate
from novel_flywheel.quality import issue_ledger
from novel_flywheel.quality_summary import effective_han_characters
from novel_flywheel.quality_records import (
    load_quality_checkpoint,
    reconcile_legacy_checkpoint,
    write_quality_checkpoint,
)
from novel_flywheel.repair_records import RepairRunStore, repair_artifact_hash
from novel_flywheel.revision import apply_patch_group
from novel_flywheel.revision_operations import RevisionOperationError
from novel_flywheel.secrets import MemorySecretStore
from novel_flywheel.storage import ProjectSnapshot
from novel_flywheel.story_state import StoryStateStore


def _revision_app(tmp_path, monkeypatch):
    db = Database(tmp_path / "app.db")
    app = create_app(
        db, MemorySecretStore(), skill_roots=[],
        workspace_root=tmp_path / "workspace",
    )
    source = (
        "雨落在旧城石阶上。林晚核对证词，发现时间写错了。" * 80
        + "记录末尾有唯一  空格。证词时间是十点。"
    )
    project = app.state.projects.create(ProjectCreate(
        title="Targeted repair",
        mode="short",
        genre="suspense",
        premise="A witness changes one crucial detail.",
        target_words=effective_han_characters(source),
    ))
    source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
    ledger = issue_ledger([
        {
            "issue_id": "issue-time",
            "category": "logic_continuity",
            "severity": "major",
            "evidence": "时间写错了",
            "action": "统一证词时间",
            "status": "unresolved",
        },
        {
            "issue_id": "issue-format",
            "category": "format",
            "severity": "minor",
            "evidence": "唯一  空格",
            "action": "删除多余空格",
            "status": "unresolved",
        },
    ])
    quality_run = "quality-source"
    db.create_run(quality_run, project.id, "short-story", status="completed")
    quality_path = project.path / "runs" / quality_run
    outputs = quality_path / "outputs"
    outputs.mkdir(parents=True)
    (outputs / "best-candidate.md").write_text(source, encoding="utf-8")
    review = {
        "score": 82,
        "dimensions": {"commercial": 82, "story": 82, "prose": 82},
        "decision": "revise",
        "hard_fail": False,
        "issues": ledger,
    }
    write_quality_checkpoint(quality_path, {
        "manuscript_path": "outputs/best-candidate.md",
        "manuscript_hash": source_hash,
        "score": 82,
        "scoring_profile_id": "legacy-v1",
        "judge_signature": "fake/reviewer",
        "best_attempt": 1,
        "review": review,
        "issue_ledger": ledger,
        "outcome": "conditional_pass",
        "terminal_reviewed_hash": source_hash,
    })
    formal = project.path / "manuscript" / "story.md"
    formal.write_text("正式稿原文不得改变。", encoding="utf-8")
    StoryStateStore(db).ensure(project.id, project.path)
    calls = []

    async def run_short_revision(project_id, issue_ids, run_id=None):
        calls.append((project_id, list(issue_ids), run_id))
        return {
            "id": run_id,
            "project_id": project_id,
            "workflow": "short-revision",
            "status": "waiting_confirmation",
        }

    monkeypatch.setattr(
        app.state.workflows, "run_short_revision", run_short_revision,
        raising=False,
    )
    return app, db, project, source, source_hash, ledger, calls


def _write_resume_records(project, run_id, source, source_hash, ledger) -> None:
    run_path = project.path / "runs" / run_id
    records = RepairRunStore(run_path)
    contract = {
        "version": 1,
        "manuscript_hash": source_hash,
        "source_run_id": "quality-source",
        "terminal_reviewed_hash": source_hash,
        "selected_issue_ids": ["issue-time"],
        "selected_issues": ledger,
        "story_state": {"revision": 1, "data": {}},
        "passage_locks": [],
        "groups": [],
    }
    groups = {"version": 1, "groups": []}
    records.write_contract(contract)
    records.write_groups(groups)
    records.write_candidate(source)
    records.write_checkpoint({
        "version": 1,
        "status": "failed",
        "source_hash": source_hash,
        "contract_hash": repair_artifact_hash(contract),
        "groups_hash": repair_artifact_hash(groups),
        "candidate_hash": repair_artifact_hash(source),
        "completed_groups": [],
    })


def _write_decision_records(app, db, project, source, source_hash, ledger):
    run_id = "repair-decisions"
    db.create_run(
        run_id, project.id, "short-revision", status="waiting_confirmation",
    )
    story_state = StoryStateStore(db).get(project.id)
    assert story_state is not None
    group_specs = [
        {
            "group_id": "issue-format",
            "issue_ids": ["issue-format"],
            "kind": "mechanical",
            "requires_user_confirmation": False,
        },
        {
            "group_id": "issue-time",
            "issue_ids": ["issue-time"],
            "kind": "semantic",
            "requires_user_confirmation": True,
        },
    ]
    contract = {
        "version": 1,
        "manuscript_hash": source_hash,
        "source_run_id": "quality-source",
        "terminal_reviewed_hash": source_hash,
        "selected_issue_ids": ["issue-format", "issue-time"],
        "selected_issues": ledger,
        "issue_ledger": ledger,
        "story_state": {
            "revision": story_state.revision,
            "data": story_state.data,
        },
        "passage_locks": db.list_locks(project.id),
        "required_text": [],
        "forbidden_text": [],
        "analysis": analyze_manuscript(source, nlp_analyze=None),
        "groups": group_specs,
    }
    mechanical_group = {
        **group_specs[0],
        "impact_flags": [],
        "patches": [{
            "operation": "replace",
            "old_text": "唯一  空格",
            "new_text": "唯一空格",
        }],
    }
    mechanical_result = {
        "group_id": "issue-format",
        **apply_patch_group(source, mechanical_group, source_hash),
    }
    mechanical_text = mechanical_result["text"]
    semantic_group = {
        **group_specs[1],
        "impact_flags": [],
        "patches": [{
            "operation": "replace",
            "old_text": "证词时间是十点",
            "new_text": "证词时间是九点",
        }],
    }
    semantic_result = {
        "group_id": "issue-time",
        **apply_patch_group(
            mechanical_text, semantic_group, repair_artifact_hash(mechanical_text),
        ),
    }
    candidate = semantic_result["text"]
    records_value = [{
        **group_specs[0],
        "status": "ready_for_confirmation",
        "attempts": 1,
        "message": "机械修复已应用到候选稿",
        "patch_group": mechanical_group,
        "patch_result": mechanical_result,
    }, {
        **group_specs[1],
        "status": "ready_for_confirmation",
        "attempts": 1,
        "message": "语义修改等待确认",
        "patch_group": semantic_group,
        "patch_result": semantic_result,
    }]
    groups = {"groups": records_value}
    store = RepairRunStore(project.path / "runs" / run_id)
    store.write_contract(contract)
    store.write_groups(groups)
    store.write_candidate(candidate)
    store.write_checkpoint({
        "version": 1,
        "status": "waiting_confirmation",
        "source_hash": source_hash,
        "contract_hash": repair_artifact_hash(contract),
        "groups_hash": repair_artifact_hash(groups),
        "candidate_hash": repair_artifact_hash(candidate),
        "completed_groups": ["issue-format", "issue-time"],
    })
    app.state.workflows._write_short_revision_report(
        store, run_id, records_value, candidate,
        {"passed": True, "blocking": []}, "waiting_confirmation",
    )
    return run_id, repair_artifact_hash(candidate), store


def test_start_revision_requires_a_nonempty_selection(tmp_path, monkeypatch) -> None:
    app, _db, project, *_rest = _revision_app(tmp_path, monkeypatch)
    client = TestClient(app)

    response = client.post(
        f"/api/projects/{project.id}/revisions", json={"issue_ids": []},
    )

    assert response.status_code == 422


def test_start_revision_validates_known_issues_before_dispatch(
    tmp_path, monkeypatch,
) -> None:
    app, db, project, *_rest, calls = _revision_app(tmp_path, monkeypatch)
    client = TestClient(app)

    response = client.post(
        f"/api/projects/{project.id}/revisions",
        json={"issue_ids": ["missing-issue"]},
    )

    assert response.status_code == 422
    assert not [
        run for run in db.list_runs(project.id)
        if run["workflow"] == "short-revision"
    ]
    assert calls == []


def test_start_revision_dispatches_short_revision_run(
    tmp_path, monkeypatch,
) -> None:
    app, _db, project, *_rest = _revision_app(tmp_path, monkeypatch)
    client = TestClient(app)

    response = client.post(
        f"/api/projects/{project.id}/revisions",
        json={"issue_ids": ["issue-time"]},
    )

    assert response.status_code == 202
    assert response.json()["workflow"] == "short-revision"
    assert response.json()["status"] in {"queued", "running"}


def test_revision_api_persists_minimal_selection_and_rebuilds_after_restart(
    tmp_path, monkeypatch,
) -> None:
    app, db, project, source, _source_hash, _ledger, _calls = _revision_app(
        tmp_path, monkeypatch,
    )
    formal_path = project.path / "manuscript" / "story.md"
    formal_before = formal_path.read_bytes()
    state_before = StoryStateStore(db).get(project.id)

    started = TestClient(app).post(
        f"/api/projects/{project.id}/revisions",
        json={"issue_ids": ["issue-time"]},
    )

    assert started.status_code == 202
    run_id = started.json()["id"]
    supervision = db.get_workflow_supervision(run_id)
    assert supervision is not None
    assert supervision["resume_payload"] == {"issue_ids": ["issue-time"]}
    serialized = json.dumps(supervision["resume_payload"], ensure_ascii=False)
    assert source not in serialized
    assert "api_key" not in serialized.casefold()
    assert "provider" not in serialized.casefold()

    restarted = create_app(
        db, MemorySecretStore(), skill_roots=[],
        workspace_root=tmp_path / "workspace",
    )
    resumed = []

    class RestartedWorkflows:
        async def run_short_revision(self, project_id, issue_ids, run_id=None):
            resumed.append((project_id, list(issue_ids), run_id))
            return {"status": "waiting_confirmation"}

    restarted.state.workflows = RestartedWorkflows()
    operation = restarted.state.run_tasks.operation_resolver(
        db.get_run(run_id), supervision["resume_payload"],
    )
    assert operation is not None
    asyncio.run(operation(run_id))

    assert resumed == [(project.id, ["issue-time"], run_id)]
    assert formal_path.read_bytes() == formal_before
    assert StoryStateStore(db).get(project.id) == state_before


@pytest.mark.asyncio
async def test_revision_startup_recovery_requeues_same_run_to_confirmation_boundary(
    tmp_path, monkeypatch,
) -> None:
    app, db, project, _source, _source_hash, _ledger, _calls = _revision_app(
        tmp_path, monkeypatch,
    )
    formal_path = project.path / "manuscript" / "story.md"
    protected_best = (
        project.path / "runs" / "quality-source" / "outputs" / "best-candidate.md"
    )
    formal_before = formal_path.read_bytes()
    best_before = protected_best.read_bytes()
    state_before = StoryStateStore(db).get(project.id)

    with TestClient(app) as client:
        started = client.post(
            f"/api/projects/{project.id}/revisions",
            json={"issue_ids": ["issue-time"]},
        )
        assert started.status_code == 202
        run_id = started.json()["id"]
        for _ in range(100):
            if db.get_run(run_id)["status"] not in {"queued", "running"}:
                break
            time.sleep(0.01)

    supervision = db.get_workflow_supervision(run_id)
    assert supervision is not None
    assert supervision["resume_payload"] == {"issue_ids": ["issue-time"]}
    db.update_run(run_id, "interrupted", "repair_gate")
    db.save_workflow_supervision(run_id=run_id, state="interrupted")

    restarted = create_app(
        db, MemorySecretStore(), skill_roots=[],
        workspace_root=tmp_path / "workspace",
    )
    resumed_calls = []

    class RestartedWorkflows:
        async def run_short_revision(self, project_id, issue_ids, run_id=None):
            resumed_calls.append((project_id, list(issue_ids), run_id))
            store = RepairRunStore(
                restarted.state.projects.get(project_id).path / "runs" / run_id,
            )
            store.write_checkpoint({
                "version": 1,
                "status": "waiting_confirmation",
                "selected_issue_ids": list(issue_ids),
                "resume_boundary": "repair_gate",
            })
            db.update_run(run_id, "waiting_confirmation", "repair_gate")
            return {"status": "waiting_confirmation"}

    restarted.state.workflows = RestartedWorkflows()

    scheduled = restarted.state.run_tasks.recover_due_runs()
    recovered = await restarted.state.run_tasks.wait(run_id)

    assert scheduled == [run_id]
    assert recovered["id"] == run_id
    assert recovered["status"] == "waiting_confirmation"
    assert resumed_calls == [(project.id, ["issue-time"], run_id)]
    checkpoint = json.loads((
        project.path / "runs" / run_id / "outputs" / "repair-checkpoint.json"
    ).read_text(encoding="utf-8"))
    assert checkpoint["selected_issue_ids"] == ["issue-time"]
    assert checkpoint["resume_boundary"] == "repair_gate"
    assert [
        item["action"] for item in db.list_workflow_attempts(run_id)
        if item["action"] in {"resume_validated_checkpoint", "execute_from_checkpoint"}
    ][-2:] == ["resume_validated_checkpoint", "execute_from_checkpoint"]
    assert formal_path.read_bytes() == formal_before
    assert protected_best.read_bytes() == best_before
    assert StoryStateStore(db).get(project.id) == state_before


def test_read_revision_returns_only_public_summary_fields(
    tmp_path, monkeypatch,
) -> None:
    app, db, project, _source, source_hash, _ledger, _calls = _revision_app(
        tmp_path, monkeypatch,
    )
    run_id = "repair-read"
    db.create_run(
        run_id, project.id, "short-revision", status="waiting_confirmation",
    )
    report = {
        "status": "waiting_confirmation",
        "candidate_hash": source_hash,
        "gate": {"passed": True, "reasons": []},
        "review_mode": None,
        "full_review_reasons": [],
        "next_action": "请确认语义修改",
        "provider_error": "secret upstream failure",
        "prompt": "private prompt",
        "path": str(project.path),
        "groups": [{
            "group_id": "group-1",
            "kind": "semantic",
            "status": "ready_for_confirmation",
            "decision": None,
            "message": "等待确认",
            "failures": [],
            "issue": {"issue_id": "issue-time", "action": "统一时间"},
            "before": "时间写错了",
            "after": "时间已经统一",
            "related_positions": ["开头", "结尾"],
            "local_checks": {"passed": True},
            "patches": [{"old_text": "private", "new_text": "private"}],
            "raw_model_output": "private",
        }],
    }
    RepairRunStore(project.path / "runs" / run_id).write_report(report)
    client = TestClient(app)

    response = client.get(f"/api/runs/{run_id}/revision")

    assert response.status_code == 200
    assert set(response.json()) == {
        "status", "candidate_hash", "gate", "review_mode",
        "full_review_reasons", "next_action", "groups",
    }
    assert set(response.json()["groups"][0]) == {
        "group_id", "kind", "status", "decision", "message", "failures",
        "issue", "before", "after", "related_positions", "local_checks",
    }
    assert "secret upstream failure" not in response.text
    assert str(project.path) not in response.text


def test_read_revision_recursively_projects_nested_public_fields(
    tmp_path, monkeypatch,
) -> None:
    app, db, project, _source, source_hash, _ledger, _calls = _revision_app(
        tmp_path, monkeypatch,
    )
    run_id = "repair-nested-read"
    db.create_run(
        run_id, project.id, "short-revision", status="waiting_confirmation",
    )
    sentinel = f"PRIVATE_PROVIDER C:\\secret\\provider.log {project.path}"
    RepairRunStore(project.path / "runs" / run_id).write_report({
        "candidate_hash": source_hash,
        "groups": [{
            "group_id": "group-1",
            "kind": "semantic",
            "status": "ready_for_confirmation",
            "decision": None,
            "message": "等待确认",
            "issue": {
                "issue_id": "issue-time", "status": "unresolved",
                "mandatory": True, "category": "logic", "title": "时间",
                "impact": "结尾", "evidence": "十点", "suggestion": "九点",
                "provider_error": sentinel, "prompt": sentinel,
            },
            "failures": [{
                "code": "anchor_not_unique", "message": "锚点重复",
                "patch": 2, "provider_error": sentinel, "path": sentinel,
            }],
            "related_positions": [{
                "stable_id": "paragraph-2", "start": 10, "end": 20,
                "label": "第二段", "absolute_path": sentinel,
            }],
            "local_checks": {
                "code": "whole_candidate", "passed": True,
                "message": "通过", "prompt": sentinel,
            },
        }],
    })
    response = TestClient(app).get(f"/api/runs/{run_id}/revision")

    assert response.status_code == 200
    group = response.json()["groups"][0]
    assert group["issue"] == {
        "issue_id": "issue-time", "status": "unresolved",
        "mandatory": True, "category": "logic", "title": "时间",
        "impact": "结尾", "evidence": "十点", "suggestion": "九点",
    }
    assert group["failures"] == [{
        "code": "anchor_not_unique", "message": "锚点重复", "patch": 2,
    }]
    assert group["related_positions"] == [{
        "stable_id": "paragraph-2", "start": 10, "end": 20,
        "label": "第二段",
    }]
    assert group["local_checks"] == {
        "code": "whole_candidate", "passed": True, "message": "通过",
    }
    assert sentinel not in response.text


def test_background_revision_failure_exposes_only_safe_error(
    tmp_path, monkeypatch,
) -> None:
    app, _db, project, *_rest = _revision_app(tmp_path, monkeypatch)
    sentinel = f"PROVIDER_SECRET C:\\private\\model.log {project.path}"

    async def fail_revision(*args, **kwargs):
        raise RuntimeError(sentinel)

    monkeypatch.setattr(
        app.state.workflows, "run_short_revision", fail_revision,
    )
    with TestClient(app) as client:
        started = client.post(
            f"/api/projects/{project.id}/revisions",
            json={"issue_ids": ["issue-time"]},
        )
        assert started.status_code == 202
        run_id = started.json()["id"]
        detail = None
        for _ in range(100):
            detail = client.get(f"/api/runs/{run_id}").json()
            if detail["status"] == "failed":
                break
            time.sleep(0.01)

    assert detail is not None
    assert detail["status"] == "failed"
    assert detail["error"] == "定向返修未完成，已保留可恢复进度。"
    assert detail["supervision"]["state"] in {"waiting_user", "irrecoverable"}
    assert detail["recovery_attempts"]
    assert all("failure_sha256" in item for item in detail["recovery_attempts"])
    assert sentinel not in json.dumps(detail, ensure_ascii=False)


def test_pipeline_revision_failure_exposes_no_inner_error_or_event(
    tmp_path, monkeypatch,
) -> None:
    app, _db, project, *_rest = _revision_app(tmp_path, monkeypatch)
    sentinel = "秘密路径：某盘＼私密＼模型日志；提示词：不得公开的系统提示"
    real_pipeline = app.state.workflows.__class__.run_short_revision.__get__(
        app.state.workflows,
    )

    def fail_analysis(*args, **kwargs):
        raise RuntimeError(sentinel)

    monkeypatch.setattr(app.state.workflows, "run_short_revision", real_pipeline)
    monkeypatch.setattr(app.state.workflows, "_analyze_manuscript", fail_analysis)
    with TestClient(app) as client:
        started = client.post(
            f"/api/projects/{project.id}/revisions",
            json={"issue_ids": ["issue-time"]},
        )
        assert started.status_code == 202
        run_id = started.json()["id"]
        detail = None
        for _ in range(100):
            detail = client.get(f"/api/runs/{run_id}").json()
            if detail["status"] == "failed":
                break
            time.sleep(0.01)

    assert detail is not None
    assert detail["status"] == "failed"
    assert sentinel not in json.dumps(detail, ensure_ascii=False)


@pytest.mark.parametrize(
    ("endpoint", "payload"),
    [
        ("start", {"issue_ids": []}),
        ("start", {}),
        ("decision", {"candidate_hash": "not-a-hash"}),
    ],
)
def test_revision_validation_errors_use_fixed_chinese_detail(
    tmp_path, monkeypatch, endpoint, payload,
) -> None:
    app, _db, project, *_rest = _revision_app(tmp_path, monkeypatch)
    path = (
        f"/api/projects/{project.id}/revisions"
        if endpoint == "start" else
        "/api/runs/any/revision/groups/group/adopt"
    )

    response = TestClient(app).post(path, json=payload)

    assert response.status_code == 422
    assert response.json() == {"detail": {
        "code": "revision_payload_invalid",
        "message": "返修请求格式不正确，请检查后重试。",
    }}


def test_non_revision_validation_error_keeps_fastapi_default(
    tmp_path, monkeypatch,
) -> None:
    app, _db, project, *_rest = _revision_app(tmp_path, monkeypatch)

    response = TestClient(app).post(
        f"/api/projects/{project.id}/runs/chapter", json={},
    )

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


def test_read_revision_rejects_non_revision_run(tmp_path, monkeypatch) -> None:
    app, db, project, *_rest = _revision_app(tmp_path, monkeypatch)
    db.create_run("ordinary", project.id, "short-story", status="completed")
    client = TestClient(app)

    response = client.get("/api/runs/ordinary/revision")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "revision_run_invalid"


@pytest.mark.parametrize("run_status", ["failed", "interrupted"])
def test_revision_resumes_same_run_with_frozen_selection(
    tmp_path, monkeypatch, run_status,
) -> None:
    app, db, project, source, source_hash, ledger, calls = _revision_app(
        tmp_path, monkeypatch,
    )
    run_id = f"repair-{run_status}"
    db.create_run(run_id, project.id, "short-revision", status=run_status)
    _write_resume_records(project, run_id, source, source_hash, ledger)
    client = TestClient(app)

    response = client.post(f"/api/runs/{run_id}/resume")

    assert response.status_code == 202
    assert response.json()["id"] == run_id
    assert response.json()["workflow"] == "short-revision"


def test_mechanical_group_is_adopted_without_user_decision(
    tmp_path, monkeypatch,
) -> None:
    app, db, project, source, source_hash, ledger, _calls = _revision_app(
        tmp_path, monkeypatch,
    )
    run_id, _candidate_hash, _store = _write_decision_records(
        app, db, project, source, source_hash, ledger,
    )
    client = TestClient(app)

    response = client.get(f"/api/runs/{run_id}/revision")

    mechanical = next(
        group for group in response.json()["groups"]
        if group["group_id"] == "issue-format"
    )
    assert mechanical["decision"] == "adopted"


def test_adopt_group_requires_current_candidate_hash(
    tmp_path, monkeypatch,
) -> None:
    app, db, project, source, source_hash, ledger, _calls = _revision_app(
        tmp_path, monkeypatch,
    )
    run_id, _candidate_hash, store = _write_decision_records(
        app, db, project, source, source_hash, ledger,
    )
    before = {
        name: (store.output / name).read_bytes()
        for name in (
            store.GROUPS, store.CANDIDATE, store.CHECKPOINT, store.REPORT,
        )
    }
    client = TestClient(app)

    response = client.post(
        f"/api/runs/{run_id}/revision/groups/issue-time/adopt",
        json={"candidate_hash": "0" * 64},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "revision_candidate_changed"
    assert before == {
        name: (store.output / name).read_bytes() for name in before
    }


def test_adopt_group_is_idempotent_but_opposite_decision_conflicts(
    tmp_path, monkeypatch,
) -> None:
    app, db, project, source, source_hash, ledger, _calls = _revision_app(
        tmp_path, monkeypatch,
    )
    run_id, candidate_hash, _store = _write_decision_records(
        app, db, project, source, source_hash, ledger,
    )
    client = TestClient(app)
    endpoint = f"/api/runs/{run_id}/revision/groups/issue-time"

    first = client.post(
        f"{endpoint}/adopt", json={"candidate_hash": candidate_hash},
    )
    repeated = client.post(
        f"{endpoint}/adopt", json={"candidate_hash": candidate_hash},
    )
    opposite = client.post(
        f"{endpoint}/reject", json={"candidate_hash": candidate_hash},
    )

    assert first.status_code == 200
    assert repeated.status_code == 200
    assert first.json() == repeated.json()
    assert first.json()["decision"] == "adopted"
    assert opposite.status_code == 409
    assert opposite.json()["detail"]["code"] == "revision_group_already_decided"


def test_reject_group_keeps_corresponding_issue_unresolved(
    tmp_path, monkeypatch,
) -> None:
    app, db, project, source, source_hash, ledger, _calls = _revision_app(
        tmp_path, monkeypatch,
    )
    run_id, candidate_hash, _store = _write_decision_records(
        app, db, project, source, source_hash, ledger,
    )
    client = TestClient(app)

    response = client.post(
        f"/api/runs/{run_id}/revision/groups/issue-time/reject",
        json={"candidate_hash": candidate_hash},
    )

    assert response.status_code == 200
    assert response.json()["decision"] == "rejected"
    assert response.json()["issue"]["issue_id"] == "issue-time"
    assert response.json()["issue"]["status"] == "unresolved"


def test_group_decision_rejects_missing_or_unready_group(
    tmp_path, monkeypatch,
) -> None:
    app, db, project, source, source_hash, ledger, _calls = _revision_app(
        tmp_path, monkeypatch,
    )
    run_id, candidate_hash, store = _write_decision_records(
        app, db, project, source, source_hash, ledger,
    )
    client = TestClient(app)

    missing = client.post(
        f"/api/runs/{run_id}/revision/groups/missing/adopt",
        json={"candidate_hash": candidate_hash},
    )
    groups = json.loads(
        (store.output / store.GROUPS).read_text(encoding="utf-8"),
    )
    semantic = next(
        item for item in groups["groups"]
        if item["group_id"] == "issue-time"
    )
    semantic["status"] = "failed"
    store.write_groups(groups)
    checkpoint = json.loads(
        (store.output / store.CHECKPOINT).read_text(encoding="utf-8"),
    )
    checkpoint["groups_hash"] = repair_artifact_hash(groups)
    store.write_checkpoint(checkpoint)
    unready = client.post(
        f"/api/runs/{run_id}/revision/groups/issue-time/adopt",
        json={"candidate_hash": candidate_hash},
    )

    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "revision_group_not_found"
    assert unready.status_code == 409
    assert unready.json()["detail"]["code"] == "revision_group_not_ready"


def test_group_decision_makes_zero_terminal_review_calls(
    tmp_path, monkeypatch,
) -> None:
    app, db, project, source, source_hash, ledger, _calls = _revision_app(
        tmp_path, monkeypatch,
    )
    run_id, candidate_hash, _store = _write_decision_records(
        app, db, project, source, source_hash, ledger,
    )

    async def forbidden_review(*args, **kwargs):
        raise AssertionError("group decisions must not call terminal review")

    monkeypatch.setattr(
        app.state.workflows, "_incremental_manuscript_review",
        forbidden_review,
    )
    monkeypatch.setattr(
        app.state.workflows, "_full_manuscript_review", forbidden_review,
    )
    client = TestClient(app)

    response = client.post(
        f"/api/runs/{run_id}/revision/groups/issue-time/adopt",
        json={"candidate_hash": candidate_hash},
    )

    assert response.status_code == 200


@pytest.mark.parametrize(
    "failing_write",
    ["write_groups", "write_candidate", "write_checkpoint", "write_report"],
)
def test_group_decision_write_failure_restores_all_repair_artifacts(
    tmp_path, monkeypatch, failing_write,
) -> None:
    app, db, project, source, source_hash, ledger, _calls = _revision_app(
        tmp_path, monkeypatch,
    )
    run_id, candidate_hash, store = _write_decision_records(
        app, db, project, source, source_hash, ledger,
    )
    names = (store.GROUPS, store.CANDIDATE, store.CHECKPOINT, store.REPORT)
    before = {
        name: (store.output / name).read_bytes()
        for name in names
    }

    def fail_write(*args, **kwargs):
        raise OSError("injected decision write failure")

    monkeypatch.setattr(RepairRunStore, failing_write, fail_write)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        f"/api/runs/{run_id}/revision/groups/issue-time/adopt",
        json={"candidate_hash": candidate_hash},
    )

    assert response.status_code == 500
    assert before == {
        name: (store.output / name).read_bytes()
        for name in names
    }
    resumed = store.load_resume_state(source_hash)
    group = next(
        item for item in resumed["groups"]["groups"]
        if item["group_id"] == "issue-time"
    )
    assert group.get("decision") is None


def test_concurrent_decisions_for_different_groups_are_serialized(
    tmp_path, monkeypatch,
) -> None:
    app, db, project, source, source_hash, ledger, _calls = _revision_app(
        tmp_path, monkeypatch,
    )
    run_id, candidate_hash, store = _write_decision_records(
        app, db, project, source, source_hash, ledger,
    )
    groups = json.loads(
        (store.output / store.GROUPS).read_text(encoding="utf-8"),
    )
    second = json.loads(json.dumps(groups["groups"][1]))
    second["group_id"] = "issue-time-2"
    second["patch_group"]["group_id"] = "issue-time-2"
    second["patch_result"]["group_id"] = "issue-time-2"
    groups["groups"].append(second)
    store.write_groups(groups)
    checkpoint = json.loads(
        (store.output / store.CHECKPOINT).read_text(encoding="utf-8"),
    )
    checkpoint["groups_hash"] = repair_artifact_hash(groups)
    checkpoint["completed_groups"].append("issue-time-2")
    store.write_checkpoint(checkpoint)

    workflows = app.state.workflows
    original = workflows._decide_short_revision_group
    first_entered = threading.Event()
    release_first = threading.Event()

    def controlled(run_id_arg, group_id, decision, hash_arg):
        if group_id == "issue-time":
            first_entered.set()
            assert release_first.wait(timeout=5)
        return original(run_id_arg, group_id, decision, hash_arg)

    monkeypatch.setattr(workflows, "_decide_short_revision_group", controlled)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            workflows.decide_short_revision_group,
            run_id, "issue-time", "adopted", candidate_hash,
        )
        assert first_entered.wait(timeout=5)
        second_future = executor.submit(
            workflows.decide_short_revision_group,
            run_id, "issue-time-2", "rejected", candidate_hash,
        )
        assert not second_future.done()
        release_first.set()
        assert first.result(timeout=5)["decision"] == "adopted"
        assert second_future.result(timeout=5)["decision"] == "rejected"

    state = store.load_resume_state(source_hash)
    decisions = {
        item["group_id"]: item.get("decision")
        for item in state["groups"]["groups"]
    }
    assert decisions["issue-time"] == "adopted"
    assert decisions["issue-time-2"] == "rejected"


def _passing_revision_review(ledger):
    return {
        "score": 85,
        "dimensions": {"commercial": 85, "story": 85, "prose": 85},
        "decision": "pass",
        "hard_fail": False,
        "issues": [
            {**item, "status": "resolved"}
            for item in ledger
        ],
        "scoring_profile_id": "legacy-v1",
        "judge_signature": "fake/reviewer",
    }


def test_finalize_refuses_undecided_semantic_group(
    tmp_path, monkeypatch,
) -> None:
    app, db, project, source, source_hash, ledger, _calls = _revision_app(
        tmp_path, monkeypatch,
    )
    run_id, _candidate_hash, _store = _write_decision_records(
        app, db, project, source, source_hash, ledger,
    )
    client = TestClient(app)

    response = client.post(f"/api/runs/{run_id}/revision/finalize")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "revision_decisions_incomplete"
    assert db.get_run(run_id)["status"] == "waiting_confirmation"


def test_finalize_rebuilds_from_frozen_source_and_excludes_rejected_group(
    tmp_path, monkeypatch,
) -> None:
    app, db, project, source, source_hash, ledger, _calls = _revision_app(
        tmp_path, monkeypatch,
    )
    run_id, candidate_hash, _store = _write_decision_records(
        app, db, project, source, source_hash, ledger,
    )
    source_best = (
        project.path / "runs" / "quality-source" / "outputs" / "best-candidate.md"
    )
    formal = project.path / "manuscript" / "story.md"
    protected_before = source_best.read_bytes()
    formal_before = formal.read_bytes()
    story_before = StoryStateStore(db).get(project.id)
    locks_before = db.list_locks(project.id)
    captured = {}

    async def review(
        run_id_arg, run_path, project_arg, constraints, manuscript,
        analysis, baseline, initial_review, **kwargs,
    ):
        captured["manuscript"] = manuscript
        captured["revision_source_hash"] = kwargs["revision_source_hash"]
        captured["patch_groups"] = kwargs["patch_groups"]
        captured["analysis_hash"] = analysis["text_hash"]
        return _passing_revision_review(ledger), {
            "review_mode": "incremental",
            "fallback_reasons": [],
        }

    monkeypatch.setattr(
        app.state.workflows, "_incremental_manuscript_review", review,
    )
    client = TestClient(app)
    rejected = client.post(
        f"/api/runs/{run_id}/revision/groups/issue-time/reject",
        json={"candidate_hash": candidate_hash},
    )

    response = client.post(f"/api/runs/{run_id}/revision/finalize")

    expected = source.replace("唯一  空格", "唯一空格")
    assert rejected.status_code == 200
    assert response.status_code == 200
    assert captured["manuscript"] == expected
    assert "证词时间是十点" in captured["manuscript"]
    assert captured["revision_source_hash"] == source_hash
    assert [item["group_id"] for item in captured["patch_groups"]] == [
        "issue-format",
    ]
    assert captured["analysis_hash"] == repair_artifact_hash(expected)
    checkpoint = load_quality_checkpoint(project.path / "runs" / run_id)
    assert checkpoint is not None
    assert checkpoint["manuscript_path"] == "outputs/candidate.md"
    assert checkpoint["manuscript_hash"] == repair_artifact_hash(expected)
    assert checkpoint["terminal_reviewed_hash"] == repair_artifact_hash(expected)
    rejected_issue = next(
        item for item in checkpoint["issue_ledger"]
        if item["issue_id"] == "issue-time"
    )
    assert rejected_issue["status"] == "unresolved"
    assert not (
        project.path / "runs" / run_id / "outputs" / "best-candidate.md"
    ).exists()
    assert source_best.read_bytes() == protected_before
    assert formal.read_bytes() == formal_before
    assert StoryStateStore(db).get(project.id) == story_before
    assert db.list_locks(project.id) == locks_before
    repeated = client.post(f"/api/runs/{run_id}/revision/finalize")
    assert repeated.status_code == 409
    assert repeated.json()["detail"]["code"] == "revision_already_finalized"


def test_finalize_gate_failure_calls_zero_review_models(
    tmp_path, monkeypatch,
) -> None:
    app, db, project, source, source_hash, ledger, _calls = _revision_app(
        tmp_path, monkeypatch,
    )
    run_id, candidate_hash, _store = _write_decision_records(
        app, db, project, source, source_hash, ledger,
    )
    client = TestClient(app)
    assert client.post(
        f"/api/runs/{run_id}/revision/groups/issue-time/adopt",
        json={"candidate_hash": candidate_hash},
    ).status_code == 200
    original_analyze = app.state.workflows._analyze_manuscript

    def blocked_analysis(*args, **kwargs):
        result = original_analyze(*args, **kwargs)
        result["prose"] = {**result["prose"], "blocking_count": 1}
        return result

    async def forbidden_review(*args, **kwargs):
        raise AssertionError("gate failure must happen before terminal review")

    monkeypatch.setattr(
        app.state.workflows, "_analyze_manuscript", blocked_analysis,
    )
    monkeypatch.setattr(
        app.state.workflows, "_incremental_manuscript_review",
        forbidden_review,
    )

    response = client.post(f"/api/runs/{run_id}/revision/finalize")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "revision_gate_failed"
    assert db.get_run(run_id)["status"] == "waiting_local_fix"
    summary = client.get(f"/api/runs/{run_id}/revision").json()
    assert next(
        item for item in summary["groups"]
        if item["group_id"] == "issue-time"
    )["decision"] == "adopted"


def test_finalize_rejects_stale_story_state_before_review(
    tmp_path, monkeypatch,
) -> None:
    app, db, project, source, source_hash, ledger, _calls = _revision_app(
        tmp_path, monkeypatch,
    )
    run_id, candidate_hash, _store = _write_decision_records(
        app, db, project, source, source_hash, ledger,
    )
    client = TestClient(app)
    assert client.post(
        f"/api/runs/{run_id}/revision/groups/issue-time/adopt",
        json={"candidate_hash": candidate_hash},
    ).status_code == 200
    current = app.state.workflows.story_states.get(project.id)
    assert current is not None
    monkeypatch.setattr(
        app.state.workflows.story_states,
        "get",
        lambda _project_id: SimpleNamespace(
            revision=current.revision + 1, data=current.data,
        ),
    )

    async def forbidden_review(*args, **kwargs):
        raise AssertionError("stale authority must fail before terminal review")

    monkeypatch.setattr(
        app.state.workflows, "_incremental_manuscript_review",
        forbidden_review,
    )

    response = client.post(f"/api/runs/{run_id}/revision/finalize")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "revision_story_state_changed"


def test_finalize_review_failure_preserves_decisions_and_same_run_can_retry(
    tmp_path, monkeypatch,
) -> None:
    app, db, project, source, source_hash, ledger, _calls = _revision_app(
        tmp_path, monkeypatch,
    )
    run_id, candidate_hash, _store = _write_decision_records(
        app, db, project, source, source_hash, ledger,
    )
    client = TestClient(app)
    assert client.post(
        f"/api/runs/{run_id}/revision/groups/issue-time/adopt",
        json={"candidate_hash": candidate_hash},
    ).status_code == 200
    attempts = 0

    async def flaky_review(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("private provider failure")
        return _passing_revision_review(ledger), {
            "review_mode": "incremental",
            "fallback_reasons": [],
        }

    monkeypatch.setattr(
        app.state.workflows, "_incremental_manuscript_review", flaky_review,
    )

    failed = client.post(f"/api/runs/{run_id}/revision/finalize")

    assert failed.status_code == 502
    assert failed.json()["detail"] == {
        "code": "revision_review_unavailable",
        "message": "终审暂时不可用，已保留修改决定，请稍后重试。",
    }
    assert "private provider failure" not in failed.text
    assert db.get_run(run_id)["status"] == "failed"
    terminal = next(
        item for item in reversed(db.list_run_events(run_id))
        if item["event_type"] == "short_revision_failed"
    )
    assert terminal["metadata"]["incident_family"] == "review.final_review_unavailable"
    summary = client.get(f"/api/runs/{run_id}/revision").json()
    assert next(
        item for item in summary["groups"]
        if item["group_id"] == "issue-time"
    )["decision"] == "adopted"
    assert load_quality_checkpoint(project.path / "runs" / run_id) is None

    retried = client.post(f"/api/runs/{run_id}/revision/finalize")

    assert retried.status_code == 200
    assert db.get_run(run_id)["status"] == "completed"
    assert attempts == 2


@pytest.mark.parametrize("failure_point", ["analysis", "constraints"])
def test_finalize_local_failure_preserves_decisions_and_same_run_can_retry(
    tmp_path, monkeypatch, failure_point,
) -> None:
    app, db, project, source, source_hash, ledger, _calls = _revision_app(
        tmp_path, monkeypatch,
    )
    run_id, candidate_hash, _store = _write_decision_records(
        app, db, project, source, source_hash, ledger,
    )
    client = TestClient(app, raise_server_exceptions=False)
    assert client.post(
        f"/api/runs/{run_id}/revision/groups/issue-time/adopt",
        json={"candidate_hash": candidate_hash},
    ).status_code == 200
    failed_once = False

    if failure_point == "analysis":
        original_analyze = app.state.workflows._analyze_manuscript

        def flaky_analyze(*args, **kwargs):
            nonlocal failed_once
            if not failed_once:
                failed_once = True
                raise OSError("injected analysis failure")
            return original_analyze(*args, **kwargs)

        monkeypatch.setattr(
            app.state.workflows, "_analyze_manuscript", flaky_analyze,
        )
    else:
        original_read_text = Path.read_text

        def flaky_read_text(path, *args, **kwargs):
            nonlocal failed_once
            if path.name == "constraints.md" and not failed_once:
                failed_once = True
                raise OSError("injected constraints failure")
            return original_read_text(path, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", flaky_read_text)

    async def review(*args, **kwargs):
        return _passing_revision_review(ledger), {
            "review_mode": "incremental",
            "fallback_reasons": [],
        }

    monkeypatch.setattr(
        app.state.workflows, "_incremental_manuscript_review", review,
    )

    failed = client.post(f"/api/runs/{run_id}/revision/finalize")

    assert failed.status_code == 500
    assert db.get_run(run_id)["status"] == "failed"
    summary = client.get(f"/api/runs/{run_id}/revision").json()
    assert next(
        item for item in summary["groups"]
        if item["group_id"] == "issue-time"
    )["decision"] == "adopted"
    assert load_quality_checkpoint(project.path / "runs" / run_id) is None

    retried = client.post(f"/api/runs/{run_id}/revision/finalize")

    assert retried.status_code == 200
    assert db.get_run(run_id)["status"] == "completed"


def test_finalize_quality_checkpoint_failure_rolls_back_and_can_retry(
    tmp_path, monkeypatch,
) -> None:
    app, db, project, source, source_hash, ledger, _calls = _revision_app(
        tmp_path, monkeypatch,
    )
    run_id, candidate_hash, store = _write_decision_records(
        app, db, project, source, source_hash, ledger,
    )
    client = TestClient(app, raise_server_exceptions=False)
    assert client.post(
        f"/api/runs/{run_id}/revision/groups/issue-time/adopt",
        json={"candidate_hash": candidate_hash},
    ).status_code == 200
    repair_names = (store.CANDIDATE, store.CHECKPOINT, store.REPORT)
    before = {
        name: (store.output / name).read_bytes() for name in repair_names
    }
    protected = (
        project.path / "runs" / "quality-source" / "outputs"
        / "best-candidate.md"
    ).read_bytes()
    formal = (project.path / "manuscript" / "story.md").read_bytes()
    story = StoryStateStore(db).get(project.id)
    locks = db.list_locks(project.id)
    original_write = __import__(
        "novel_flywheel.workflows", fromlist=["write_quality_checkpoint"],
    ).write_quality_checkpoint
    failed_once = False

    def flaky_write(*args, **kwargs):
        nonlocal failed_once
        if not failed_once:
            failed_once = True
            raise OSError("injected quality checkpoint failure")
        return original_write(*args, **kwargs)

    monkeypatch.setattr(
        "novel_flywheel.workflows.write_quality_checkpoint", flaky_write,
    )

    async def review(*args, **kwargs):
        return _passing_revision_review(ledger), {
            "review_mode": "incremental",
            "fallback_reasons": [],
        }

    monkeypatch.setattr(
        app.state.workflows, "_incremental_manuscript_review", review,
    )

    failed = client.post(f"/api/runs/{run_id}/revision/finalize")

    assert failed.status_code == 500
    assert db.get_run(run_id)["status"] == "failed"
    assert load_quality_checkpoint(project.path / "runs" / run_id) is None
    assert before == {
        name: (store.output / name).read_bytes() for name in repair_names
    }
    assert protected == (
        project.path / "runs" / "quality-source" / "outputs"
        / "best-candidate.md"
    ).read_bytes()
    assert formal == (project.path / "manuscript" / "story.md").read_bytes()
    assert StoryStateStore(db).get(project.id) == story
    assert db.list_locks(project.id) == locks

    retried = client.post(f"/api/runs/{run_id}/revision/finalize")

    assert retried.status_code == 200
    assert db.get_run(run_id)["status"] == "completed"


@pytest.mark.parametrize(
    ("owner", "method"),
    [
        (RepairRunStore, "write_candidate"),
        (RepairRunStore, "write_checkpoint"),
        (RepairRunStore, "write_report"),
        ("workflows", "write_quality_checkpoint"),
    ],
)
def test_hard_stop_during_promotion_recovers_and_resumes_same_run(
    tmp_path, monkeypatch, owner, method,
) -> None:
    app, db, project, source, source_hash, ledger, _calls = _revision_app(
        tmp_path, monkeypatch,
    )
    run_id, candidate_hash, _store = _write_decision_records(
        app, db, project, source, source_hash, ledger,
    )
    client = TestClient(app)
    assert client.post(
        f"/api/runs/{run_id}/revision/groups/issue-time/adopt",
        json={"candidate_hash": candidate_hash},
    ).status_code == 200
    protected_path = (
        project.path / "runs" / "quality-source" / "outputs"
        / "best-candidate.md"
    )
    formal_path = project.path / "manuscript" / "story.md"
    protected_before = protected_path.read_bytes()
    formal_before = formal_path.read_bytes()
    story_before = StoryStateStore(db).get(project.id)
    locks_before = db.list_locks(project.id)

    async def review(*args, **kwargs):
        return _passing_revision_review(ledger), {
            "review_mode": "incremental", "fallback_reasons": [],
        }

    monkeypatch.setattr(
        app.state.workflows, "_incremental_manuscript_review", review,
    )

    class HardStop(BaseException):
        pass

    if owner == "workflows":
        module = __import__("novel_flywheel.workflows", fromlist=[method])
        original = getattr(module, method)

        def hard_stop(*args, **kwargs):
            original(*args, **kwargs)
            raise HardStop

        monkeypatch.setattr(module, method, hard_stop)
    else:
        original = getattr(owner, method)

        def hard_stop(instance, *args, **kwargs):
            original(instance, *args, **kwargs)
            raise HardStop

        monkeypatch.setattr(owner, method, hard_stop)

    with pytest.raises(HardStop):
        asyncio.run(app.state.workflows.finalize_short_revision(run_id))
    monkeypatch.setattr(
        __import__("novel_flywheel.workflows", fromlist=[method])
        if owner == "workflows" else owner,
        method, original,
    )
    assert db.get_run(run_id)["status"] == "running"

    fresh = create_app(
        db, MemorySecretStore(), skill_roots=[],
        workspace_root=tmp_path / "workspace",
    )
    fresh_client = TestClient(fresh)

    resumed = fresh_client.post(f"/api/runs/{run_id}/resume")

    assert resumed.status_code == 202
    assert resumed.json()["id"] == run_id
    stable = None
    for _ in range(100):
        stable = fresh_client.get(f"/api/runs/{run_id}").json()
        if stable["status"] in {
            "waiting_confirmation", "waiting_local_fix", "completed",
        }:
            break
        time.sleep(0.01)
    assert stable is not None
    assert stable["status"] in {
        "waiting_confirmation", "waiting_local_fix", "completed",
    }
    assert protected_path.read_bytes() == protected_before
    assert formal_path.read_bytes() == formal_before
    assert StoryStateStore(db).get(project.id) == story_before
    assert db.list_locks(project.id) == locks_before


def test_hard_stop_during_journal_discard_recovers_from_marker(
    tmp_path, monkeypatch,
) -> None:
    app, db, project, source, source_hash, ledger, _calls = _revision_app(
        tmp_path, monkeypatch,
    )
    run_id, candidate_hash, _store = _write_decision_records(
        app, db, project, source, source_hash, ledger,
    )
    assert TestClient(app).post(
        f"/api/runs/{run_id}/revision/groups/issue-time/adopt",
        json={"candidate_hash": candidate_hash},
    ).status_code == 200

    async def review(*args, **kwargs):
        return _passing_revision_review(ledger), {
            "review_mode": "incremental", "fallback_reasons": [],
        }

    monkeypatch.setattr(
        app.state.workflows, "_incremental_manuscript_review", review,
    )
    original = ProjectSnapshot.discard

    class HardStop(BaseException):
        pass

    def hard_stop(_snapshot):
        raise HardStop

    monkeypatch.setattr(ProjectSnapshot, "discard", hard_stop)
    with pytest.raises(HardStop):
        asyncio.run(app.state.workflows.finalize_short_revision(run_id))
    monkeypatch.setattr(ProjectSnapshot, "discard", original)
    journal = project.path / "snapshots" / f"revision-promotion-{run_id}"
    assert db.get_run(run_id)["status"] == "completed"
    assert journal.is_dir()

    fresh = create_app(
        db, MemorySecretStore(), skill_roots=[],
        workspace_root=tmp_path / "workspace",
    )
    response = TestClient(fresh).post(f"/api/runs/{run_id}/resume")

    assert response.status_code == 202
    assert response.json()["status"] == "completed"
    assert not journal.exists()


def test_promotion_recovery_waits_for_active_promotion(
    tmp_path, monkeypatch,
) -> None:
    app, db, project, source, source_hash, ledger, _calls = _revision_app(
        tmp_path, monkeypatch,
    )
    run_id, _candidate_hash, store = _write_decision_records(
        app, db, project, source, source_hash, ledger,
    )
    candidate_path = store.output / store.CANDIDATE
    original = candidate_path.read_text(encoding="utf-8")
    journal_path = (
        project.path / "snapshots" / f"revision-promotion-{run_id}"
    )
    ProjectSnapshot.create(
        project.path, journal_path, [candidate_path],
    )
    candidate_path.write_text("partial promotion", encoding="utf-8")
    module = __import__(
        "novel_flywheel.quality_records", fromlist=["QUALITY_CHECKPOINT_LOCK"],
    )
    started = threading.Event()

    def recover():
        started.set()
        return app.state.workflows.recover_short_revision_promotion(run_id)

    module.QUALITY_CHECKPOINT_LOCK.acquire()
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(recover)
            assert started.wait(timeout=5)
            time.sleep(0.05)
            assert not future.done()
            assert candidate_path.read_text(encoding="utf-8") == "partial promotion"
            assert journal_path.is_dir()
            module.QUALITY_CHECKPOINT_LOCK.release()
            assert future.result(timeout=5) is False
    finally:
        try:
            module.QUALITY_CHECKPOINT_LOCK.release()
        except RuntimeError:
            pass

    assert candidate_path.read_text(encoding="utf-8") == original
    assert not journal_path.exists()


@pytest.mark.parametrize("manifest", [None, "not-json"])
def test_marker_recovery_ignores_missing_or_corrupt_journal_manifest(
    tmp_path, monkeypatch, manifest,
) -> None:
    app, db, project, source, source_hash, ledger, _calls = _revision_app(
        tmp_path, monkeypatch,
    )
    run_id, _candidate_hash, store = _write_decision_records(
        app, db, project, source, source_hash, ledger,
    )
    candidate = (store.output / store.CANDIDATE).read_text(encoding="utf-8")
    digest = repair_artifact_hash(candidate)
    write_quality_checkpoint(project.path / "runs" / run_id, {
        "manuscript_path": "outputs/candidate.md",
        "manuscript_hash": digest,
        "score": 88,
        "scoring_profile_id": "legacy-v1",
        "judge_signature": "fake/reviewer",
        "best_attempt": 1,
        "review": _passing_revision_review(ledger),
        "issue_ledger": ledger,
        "outcome": "passed",
        "terminal_reviewed_hash": digest,
    })
    journal = project.path / "snapshots" / f"revision-promotion-{run_id}"
    journal.mkdir(parents=True)
    if manifest is not None:
        (journal / "manifest.json").write_text(manifest, encoding="utf-8")

    assert app.state.workflows.recover_short_revision_promotion(run_id) is True
    assert db.get_run(run_id)["status"] == "completed"
    assert not journal.exists()


def test_recovery_discards_partial_snapshot_creation_without_marker(
    tmp_path, monkeypatch,
) -> None:
    app, db, project, source, source_hash, ledger, _calls = _revision_app(
        tmp_path, monkeypatch,
    )
    run_id, _candidate_hash, store = _write_decision_records(
        app, db, project, source, source_hash, ledger,
    )
    before = (store.output / store.CANDIDATE).read_text(encoding="utf-8")
    journal = project.path / "snapshots" / f"revision-promotion-{run_id}"
    (journal / "files").mkdir(parents=True)

    assert app.state.workflows.recover_short_revision_promotion(run_id) is False
    assert (store.output / store.CANDIDATE).read_text(encoding="utf-8") == before
    assert db.get_run(run_id)["status"] == "waiting_confirmation"
    assert not journal.exists()


def test_recovery_discards_truncated_unicode_manifest_and_resumes(
    tmp_path, monkeypatch,
) -> None:
    app, db, project, source, source_hash, ledger, _calls = _revision_app(
        tmp_path, monkeypatch,
    )
    run_id, _candidate_hash, store = _write_decision_records(
        app, db, project, source, source_hash, ledger,
    )
    tracked = [
        store.output / name for name in (
            store.CONTRACT, store.GROUPS, store.CHECKPOINT,
            store.CANDIDATE, store.REPORT,
        )
    ]
    before = {path: path.read_bytes() for path in tracked}
    db.update_run(run_id, "interrupted", "revision_promotion")
    journal = project.path / "snapshots" / f"revision-promotion-{run_id}"
    journal.mkdir(parents=True)
    (journal / "manifest.json").write_bytes(b'["\xe4')

    with pytest.raises(ValueError, match="Snapshot manifest is invalid"):
        ProjectSnapshot.load(project.path, journal)
    assert app.state.workflows.recover_short_revision_promotion(run_id) is False
    assert {path: path.read_bytes() for path in tracked} == before
    assert not journal.exists()

    with TestClient(app) as client:
        response = client.post(f"/api/runs/{run_id}/resume")
        assert response.status_code == 202
        detail = None
        for _ in range(100):
            detail = client.get(f"/api/runs/{run_id}").json()
            if detail["status"] in {"waiting_confirmation", "completed"}:
                break
            time.sleep(0.01)

    assert detail is not None
    assert detail["status"] in {"waiting_confirmation", "completed"}


def _stub_stage_skills(monkeypatch, workflows) -> None:
    empty = SimpleNamespace(prompt="", receipts=[])
    monkeypatch.setattr(
        workflows.skills, "run_required", lambda *args, **kwargs: empty,
    )
    if hasattr(workflows.skills, "load_optional_prompts"):
        monkeypatch.setattr(
            workflows.skills, "load_optional_prompts",
            lambda *args, **kwargs: empty,
        )


def test_semantic_revision_stage_failure_exposes_no_raw_error(
    tmp_path, monkeypatch,
) -> None:
    app, _db, project, *_rest = _revision_app(tmp_path, monkeypatch)
    sentinel = "秘密路径：某盘＼私密＼供应商日志；提示词：不得公开的模型提示"
    real_pipeline = app.state.workflows.__class__.run_short_revision.__get__(
        app.state.workflows,
    )

    class FailingGateway:
        async def complete(self, *args, **kwargs):
            raise RuntimeError(sentinel)

    monkeypatch.setattr(app.state.workflows, "run_short_revision", real_pipeline)
    monkeypatch.setattr(app.state.workflows, "gateway", FailingGateway())
    _stub_stage_skills(monkeypatch, app.state.workflows)
    with TestClient(app) as client:
        started = client.post(
            f"/api/projects/{project.id}/revisions",
            json={"issue_ids": ["issue-time"]},
        )
        assert started.status_code == 202
        run_id = started.json()["id"]
        detail = None
        for _ in range(100):
            detail = client.get(f"/api/runs/{run_id}").json()
            if detail["status"] == "failed":
                break
            time.sleep(0.01)

    assert detail is not None
    assert detail["status"] == "failed"
    assert sentinel not in str(detail.get("error"))
    assert all(
        sentinel not in event["message"]
        and sentinel not in json.dumps(event["metadata"], ensure_ascii=False)
        for event in detail["events"]
    )
    assert sentinel not in json.dumps(detail["tool_receipts"], ensure_ascii=False)


@pytest.mark.parametrize("role_fallback", [False, True])
def test_revision_stage_fallback_events_omit_raw_primary_error(
    tmp_path, monkeypatch, role_fallback,
) -> None:
    app, db, project, *_rest = _revision_app(tmp_path, monkeypatch)
    sentinel = "秘密路径：某盘＼私密＼供应商日志；提示词：不得公开的模型提示"
    run_id = f"repair-stage-fallback-{role_fallback}"
    db.create_run(run_id, project.id, "short-revision", status="running")
    run_path = project.path / "runs" / run_id
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()
    _stub_stage_skills(monkeypatch, app.state.workflows)

    class FallbackGateway:
        calls = 0

        async def complete(self, *args, **kwargs):
            self.calls += 1
            if role_fallback and self.calls == 1:
                raise RuntimeError(sentinel)
            return ModelResult("safe output", {
                "provider_id": "backup-provider",
                "model_id": "backup-model",
                "model_name": "backup-name",
                "fallback_used": not role_fallback,
                "fallback_from_provider_id": "primary-provider",
                "fallback_from_model_id": "primary-model",
                "primary_error": sentinel,
            })

    monkeypatch.setattr(app.state.workflows, "gateway", FallbackGateway())
    if role_fallback:
        asyncio.run(app.state.workflows._stage_with_role_fallback(
            run_id, run_path, project, "revision_plan", "constraints", "request",
            fallback_role="review", allow_tools=False,
        ))
    else:
        asyncio.run(app.state.workflows._stage(
            run_id, run_path, project, "revision_plan", "constraints", "request",
            allow_tools=False,
        ))
    detail = TestClient(app).get(f"/api/runs/{run_id}").json()

    assert all(
        sentinel not in event["message"]
        and sentinel not in json.dumps(event["metadata"], ensure_ascii=False)
        for event in detail["events"]
    )
    assert sentinel not in json.dumps(detail["tool_receipts"], ensure_ascii=False)


def test_finalize_rejects_decision_bound_to_another_candidate_before_review(
    tmp_path, monkeypatch,
) -> None:
    app, db, project, source, source_hash, ledger, _calls = _revision_app(
        tmp_path, monkeypatch,
    )
    run_id, candidate_hash, store = _write_decision_records(
        app, db, project, source, source_hash, ledger,
    )
    client = TestClient(app)
    assert client.post(
        f"/api/runs/{run_id}/revision/groups/issue-time/adopt",
        json={"candidate_hash": candidate_hash},
    ).status_code == 200
    groups = json.loads(
        (store.output / store.GROUPS).read_text(encoding="utf-8"),
    )
    semantic = next(
        item for item in groups["groups"]
        if item["group_id"] == "issue-time"
    )
    semantic["decision_candidate_hash"] = "0" * 64
    store.write_groups(groups)
    checkpoint = json.loads(
        (store.output / store.CHECKPOINT).read_text(encoding="utf-8"),
    )
    checkpoint["groups_hash"] = repair_artifact_hash(groups)
    store.write_checkpoint(checkpoint)

    async def forbidden_review(*args, **kwargs):
        raise AssertionError("stale decision must fail before terminal review")

    monkeypatch.setattr(
        app.state.workflows, "_incremental_manuscript_review",
        forbidden_review,
    )

    response = client.post(f"/api/runs/{run_id}/revision/finalize")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "revision_candidate_changed"


@pytest.mark.parametrize(
    ("stale_authority", "expected_code"),
    [
        ("candidate", "revision_candidate_changed"),
        ("source", "revision_source_changed"),
        ("locks", "revision_locks_changed"),
    ],
)
def test_finalize_rejects_stale_authority_before_review(
    tmp_path, monkeypatch, stale_authority, expected_code,
) -> None:
    app, db, project, source, source_hash, ledger, _calls = _revision_app(
        tmp_path, monkeypatch,
    )
    run_id, candidate_hash, store = _write_decision_records(
        app, db, project, source, source_hash, ledger,
    )
    client = TestClient(app)
    assert client.post(
        f"/api/runs/{run_id}/revision/groups/issue-time/adopt",
        json={"candidate_hash": candidate_hash},
    ).status_code == 200

    if stale_authority == "candidate":
        store.write_candidate(source + "changed")
    elif stale_authority == "source":
        (project.path / "runs" / "quality-source" / "outputs"
         / "best-candidate.md").write_text(source + "changed", encoding="utf-8")
    else:
        db.save_lock(project.id, "fact.new", "changed", "test")

    async def forbidden_review(*args, **kwargs):
        raise AssertionError("stale authority must fail before terminal review")

    monkeypatch.setattr(
        app.state.workflows, "_incremental_manuscript_review",
        forbidden_review,
    )

    response = client.post(f"/api/runs/{run_id}/revision/finalize")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == expected_code


@pytest.mark.parametrize(
    ("changed_authority", "expected_code"),
    [
        ("story", "revision_story_state_changed"),
        ("locks", "revision_locks_changed"),
        ("checkpoint", "revision_source_changed"),
    ],
)
def test_finalize_rechecks_authority_after_review_before_promotion(
    tmp_path, monkeypatch, changed_authority, expected_code,
) -> None:
    app, db, project, source, source_hash, ledger, _calls = _revision_app(
        tmp_path, monkeypatch,
    )
    run_id, candidate_hash, _store = _write_decision_records(
        app, db, project, source, source_hash, ledger,
    )
    client = TestClient(app)
    assert client.post(
        f"/api/runs/{run_id}/revision/groups/issue-time/adopt",
        json={"candidate_hash": candidate_hash},
    ).status_code == 200
    current_story = app.state.workflows.story_states.get(project.id)
    assert current_story is not None
    story_changed = False
    if changed_authority == "story":
        monkeypatch.setattr(
            app.state.workflows.story_states,
            "get",
            lambda _project_id: SimpleNamespace(
                revision=(current_story.revision + 1 if story_changed
                          else current_story.revision),
                data=current_story.data,
            ),
        )

    async def review(*args, **kwargs):
        nonlocal story_changed
        if changed_authority == "story":
            story_changed = True
        elif changed_authority == "locks":
            db.save_lock(project.id, "fact.review", "changed", "test")
        else:
            other_run = "quality-during-review"
            db.create_run(
                other_run, project.id, "short-story", status="completed",
            )
            other_path = project.path / "runs" / other_run
            output = other_path / "outputs"
            output.mkdir(parents=True)
            other_source = source + "新终审稿"
            other_hash = repair_artifact_hash(other_source)
            (output / "best-candidate.md").write_text(
                other_source, encoding="utf-8",
            )
            other_review = {
                **_passing_revision_review(ledger),
                "score": 90,
                "dimensions": {
                    "commercial": 90, "story": 90, "prose": 90,
                },
            }
            write_quality_checkpoint(other_path, {
                "manuscript_path": "outputs/best-candidate.md",
                "manuscript_hash": other_hash,
                "score": 90,
                "scoring_profile_id": "legacy-v1",
                "judge_signature": "fake/reviewer",
                "best_attempt": 1,
                "review": other_review,
                "issue_ledger": ledger,
                "outcome": "pass",
                "terminal_reviewed_hash": other_hash,
            })
        return _passing_revision_review(ledger), {
            "review_mode": "incremental",
            "fallback_reasons": [],
        }

    monkeypatch.setattr(
        app.state.workflows, "_incremental_manuscript_review", review,
    )

    response = client.post(f"/api/runs/{run_id}/revision/finalize")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == expected_code
    assert db.get_run(run_id)["status"] == "failed"
    assert load_quality_checkpoint(project.path / "runs" / run_id) is None


def test_protected_revision_source_keeps_higher_scoring_checkpoint(
    tmp_path, monkeypatch,
) -> None:
    app, db, project, source, _source_hash, ledger, _calls = _revision_app(
        tmp_path, monkeypatch,
    )
    lower_run = "newer-lower-score"
    db.create_run(lower_run, project.id, "short-story", status="completed")
    lower_path = project.path / "runs" / lower_run
    output = lower_path / "outputs"
    output.mkdir(parents=True)
    lower_source = source + "较低分稿"
    lower_hash = repair_artifact_hash(lower_source)
    (output / "best-candidate.md").write_text(lower_source, encoding="utf-8")
    lower_review = {
        **_passing_revision_review(ledger),
        "score": 80,
        "dimensions": {"commercial": 80, "story": 80, "prose": 80},
    }
    write_quality_checkpoint(lower_path, {
        "manuscript_path": "outputs/best-candidate.md",
        "manuscript_hash": lower_hash,
        "score": 80,
        "scoring_profile_id": "legacy-v1",
        "judge_signature": "fake/reviewer",
        "best_attempt": 1,
        "review": lower_review,
        "issue_ledger": ledger,
        "outcome": "pass",
        "terminal_reviewed_hash": lower_hash,
    })

    protected = app.state.workflows._protected_short_revision_source(project)

    assert protected["run_id"] == "quality-source"
    assert protected["source"] == source
    assert protected["checkpoint"]["score"] == 82


def test_regular_quality_checkpoint_uses_shared_promotion_lock(
    tmp_path, monkeypatch,
) -> None:
    app, _db, project, _source, _source_hash, ledger, _calls = _revision_app(
        tmp_path, monkeypatch,
    )
    module = __import__(
        "novel_flywheel.quality_records", fromlist=["QUALITY_CHECKPOINT_LOCK"],
    )
    run_path = project.path / "runs" / "other-quality"
    started = threading.Event()

    def write_checkpoint():
        started.set()
        app.state.workflows._save_quality_checkpoint(
            run_path, "另一份终审稿", _passing_revision_review(ledger),
            1, "passed",
        )

    module.QUALITY_CHECKPOINT_LOCK.acquire()
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(write_checkpoint)
            assert started.wait(timeout=5)
            assert not future.done()
            module.QUALITY_CHECKPOINT_LOCK.release()
            future.result(timeout=5)
    finally:
        try:
            module.QUALITY_CHECKPOINT_LOCK.release()
        except RuntimeError:
            pass

    assert load_quality_checkpoint(run_path) is not None


def test_legacy_reconcile_blocks_targeted_reselect_and_wins_authority(
    tmp_path, monkeypatch,
) -> None:
    app, db, project, source, source_hash, ledger, _calls = _revision_app(
        tmp_path, monkeypatch,
    )
    run_id, candidate_hash, _store = _write_decision_records(
        app, db, project, source, source_hash, ledger,
    )
    assert TestClient(app).post(
        f"/api/runs/{run_id}/revision/groups/issue-time/adopt",
        json={"candidate_hash": candidate_hash},
    ).status_code == 200

    async def review(*args, **kwargs):
        return _passing_revision_review(ledger), {
            "review_mode": "incremental", "fallback_reasons": [],
        }

    monkeypatch.setattr(
        app.state.workflows, "_incremental_manuscript_review", review,
    )
    higher_run = "legacy-reconcile-higher"
    db.create_run(higher_run, project.id, "short-story", status="completed")
    higher_path = project.path / "runs" / higher_run
    outputs = higher_path / "outputs"
    outputs.mkdir(parents=True)
    higher_text = source + "更高分终审稿"
    higher_hash = repair_artifact_hash(higher_text)
    (outputs / "best-candidate.md").write_text(higher_text, encoding="utf-8")
    higher_review = {
        **_passing_revision_review(ledger),
        "score": 95,
        "dimensions": {"commercial": 95, "story": 95, "prose": 95},
    }
    report_path = outputs / "quality-report.json"
    report_path.write_text(json.dumps({
        "best_score": 95,
        "best_attempt": 1,
        "scoring_profile_id": "legacy-v1",
        "judge_signature": "fake/reviewer",
        "terminal_reviewed_hash": higher_hash,
        "status": "passed",
        "final_attempts": [{"attempt": 1, "review": higher_review}],
    }, ensure_ascii=False), encoding="utf-8")
    records = __import__(
        "novel_flywheel.quality_records", fromlist=["_read_json"],
    )
    original_read = records._read_json
    entered = threading.Event()
    release = threading.Event()

    def blocked_read(path):
        if path == report_path:
            entered.set()
            assert release.wait(timeout=5)
        return original_read(path)

    monkeypatch.setattr(records, "_read_json", blocked_read)
    with ThreadPoolExecutor(max_workers=2) as executor:
        reconcile = executor.submit(reconcile_legacy_checkpoint, higher_path)
        assert entered.wait(timeout=5)
        finalize = executor.submit(
            lambda: asyncio.run(
                app.state.workflows.finalize_short_revision(run_id)
            )
        )
        time.sleep(0.05)
        assert not finalize.done()
        release.set()
        assert reconcile.result(timeout=5)["score"] == 95
        with pytest.raises(RevisionOperationError) as exc_info:
            finalize.result(timeout=5)

    assert exc_info.value.code == "revision_source_changed"
    assert load_quality_checkpoint(project.path / "runs" / run_id) is None


def test_finalize_reselects_protected_checkpoint_inside_promotion_lock(
    tmp_path, monkeypatch,
) -> None:
    app, db, project, source, source_hash, ledger, _calls = _revision_app(
        tmp_path, monkeypatch,
    )
    run_id, candidate_hash, _store = _write_decision_records(
        app, db, project, source, source_hash, ledger,
    )
    client = TestClient(app)
    assert client.post(
        f"/api/runs/{run_id}/revision/groups/issue-time/adopt",
        json={"candidate_hash": candidate_hash},
    ).status_code == 200

    async def review(*args, **kwargs):
        return _passing_revision_review(ledger), {
            "review_mode": "incremental", "fallback_reasons": [],
        }

    monkeypatch.setattr(
        app.state.workflows, "_incremental_manuscript_review", review,
    )
    original_commit = app.state.workflows._commit_short_revision_promotion
    inserted = False

    def interleaved_commit(*args, **kwargs):
        nonlocal inserted
        assert not inserted
        inserted = True
        other_run = "quality-before-promotion-lock"
        db.create_run(other_run, project.id, "short-story", status="completed")
        other_path = project.path / "runs" / other_run
        higher = {
            **_passing_revision_review(ledger),
            "score": 90,
            "dimensions": {"commercial": 90, "story": 90, "prose": 90},
        }
        app.state.workflows._save_quality_checkpoint(
            other_path, source + "更高分终审稿", higher, 1, "passed",
        )
        return original_commit(*args, **kwargs)

    monkeypatch.setattr(
        app.state.workflows, "_commit_short_revision_promotion",
        interleaved_commit,
    )

    response = client.post(f"/api/runs/{run_id}/revision/finalize")

    assert inserted is True
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "revision_source_changed"
    assert load_quality_checkpoint(project.path / "runs" / run_id) is None


def test_finalize_losing_concurrent_claim_calls_zero_review_models(
    tmp_path, monkeypatch,
) -> None:
    app, db, project, source, source_hash, ledger, _calls = _revision_app(
        tmp_path, monkeypatch,
    )
    run_id, candidate_hash, _store = _write_decision_records(
        app, db, project, source, source_hash, ledger,
    )
    client = TestClient(app)
    assert client.post(
        f"/api/runs/{run_id}/revision/groups/issue-time/adopt",
        json={"candidate_hash": candidate_hash},
    ).status_code == 200

    monkeypatch.setattr(db, "claim_run_status", lambda *args, **kwargs: False)

    async def forbidden_review(*args, **kwargs):
        raise AssertionError("only the request holding the claim may review")

    monkeypatch.setattr(
        app.state.workflows, "_incremental_manuscript_review",
        forbidden_review,
    )

    response = client.post(f"/api/runs/{run_id}/revision/finalize")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "revision_run_invalid"


@pytest.mark.parametrize(
    ("case", "expected_reason"),
    [
        ("score", "score_gain_below_2"),
        ("judge", "different_judge"),
        ("dimension", "dimension_regression:commercial"),
        ("major", "new_unresolved_major_issue"),
        ("mandatory", "unresolved_mandatory_issue"),
    ],
)
def test_finalize_strict_comparison_rejects_without_checkpoint(
    tmp_path, monkeypatch, case, expected_reason,
) -> None:
    app, db, project, source, source_hash, ledger, _calls = _revision_app(
        tmp_path, monkeypatch,
    )
    run_id, candidate_hash, store = _write_decision_records(
        app, db, project, source, source_hash, ledger,
    )
    client = TestClient(app)
    assert client.post(
        f"/api/runs/{run_id}/revision/groups/issue-time/adopt",
        json={"candidate_hash": candidate_hash},
    ).status_code == 200
    review = _passing_revision_review(ledger)
    if case == "score":
        review["score"] = 83
    elif case == "judge":
        review["judge_signature"] = "other/reviewer"
    elif case == "dimension":
        review["dimensions"]["commercial"] = 78
    elif case == "major":
        review["issues"].append({
            "issue_id": "new-major",
            "category": "story",
            "severity": "major",
            "status": "unresolved",
            "evidence": "new issue",
            "action": "repair",
        })
    else:
        review["issues"].append({
            "issue_id": "new-mandatory",
            "category": "compliance",
            "severity": "blocking",
            "status": "unresolved",
            "evidence": "mandatory issue",
            "action": "repair",
        })

    async def weaker_review(*args, **kwargs):
        return review, {
            "review_mode": "incremental",
            "fallback_reasons": [],
        }

    monkeypatch.setattr(
        app.state.workflows, "_incremental_manuscript_review", weaker_review,
    )

    response = client.post(f"/api/runs/{run_id}/revision/finalize")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "revision_not_improved"
    assert db.get_run(run_id)["status"] == "waiting_confirmation"
    assert load_quality_checkpoint(project.path / "runs" / run_id) is None
    report = json.loads(
        (store.output / store.REPORT).read_text(encoding="utf-8"),
    )
    assert expected_reason in report["comparison"]["reasons"]


def test_finalize_uses_real_full_review_fallback_triggers(
    tmp_path, monkeypatch,
) -> None:
    app, db, project, source, source_hash, ledger, _calls = _revision_app(
        tmp_path, monkeypatch,
    )
    run_id, candidate_hash, _store = _write_decision_records(
        app, db, project, source, source_hash, ledger,
    )
    client = TestClient(app)
    assert client.post(
        f"/api/runs/{run_id}/revision/groups/issue-time/adopt",
        json={"candidate_hash": candidate_hash},
    ).status_code == 200
    full_calls = []

    async def full_review(*args, **kwargs):
        full_calls.append(args[4])
        return _passing_revision_review(ledger), {
            "review_mode": "full",
            "fallback_reasons": [],
        }

    monkeypatch.setattr(
        app.state.workflows, "_full_manuscript_review", full_review,
    )

    response = client.post(f"/api/runs/{run_id}/revision/finalize")

    assert response.status_code == 200
    assert len(full_calls) == 1
    assert response.json()["review_mode"] == "full_fallback"
    assert response.json()["full_review_reasons"]
