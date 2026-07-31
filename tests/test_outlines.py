import json
from pathlib import Path

import pytest

from novel_flywheel.db import Database
from novel_flywheel.learning import LearningSystem
from novel_flywheel.outlines import OutlineService
from novel_flywheel.projects import ProjectCreate, ProjectStore
from novel_flywheel.reference_library import ReferenceLibrary


def setup_outline_service(tmp_path) -> tuple[Database, ProjectStore, object, OutlineService]:
    db = Database(tmp_path / "app.db")
    db.migrate()
    projects = ProjectStore(db, tmp_path / "projects")
    project = projects.create(ProjectCreate(
        title="大纲版本测试", mode="short", genre="悬疑",
        premise="主角寻找失踪的朋友", target_words=10_000,
    ))
    return db, projects, project, OutlineService(db, projects)


def test_current_outline_uses_latest_completed_run_without_migrating_it(tmp_path) -> None:
    db, _projects, project, service = setup_outline_service(tmp_path)
    for run_id, content in (("older", "# 旧大纲\n"), ("latest", "# 最近大纲\n")):
        db.create_run(run_id, project.id, "short-story", status="completed")
        output = project.path / "runs" / run_id / "outputs"
        output.mkdir(parents=True)
        (output / "planning.md").write_text(content, encoding="utf-8")

    current = service.current(project.id)

    assert current["content"] == "# 最近大纲\n"
    assert current["source"] == "legacy_run"
    assert current["outline_version"] == 0
    assert current["stage"] == "outline_only"


def test_candidate_can_be_listed_read_and_edited_instead_of_hidden_on_disk(tmp_path) -> None:
    _db, _projects, project, service = setup_outline_service(tmp_path)
    candidate = service.create_candidate(
        project.id, "# 初稿\n\n主角出发。\n", title="第一次调整",
    )

    listed = service.list_candidates(project.id)
    edited = service.update_candidate(
        project.id, candidate["id"], "# 初稿\n\n主角带着证据出发。\n", title="补充证据",
    )

    assert listed[0]["content"] == "# 初稿\n\n主角出发。\n"
    assert edited["title"] == "补充证据"
    assert service.get_candidate(project.id, candidate["id"])["content"] == "# 初稿\n\n主角带着证据出发。\n"


def test_local_comparison_reports_story_blocks_and_does_not_need_a_model(tmp_path) -> None:
    _db, _projects, project, service = setup_outline_service(tmp_path)
    first = service.create_candidate(
        project.id,
        "# 大纲\n\n## 开头\n主角收到求救信。\n\n## 结尾\n主角救回朋友。\n",
    )
    service.apply_candidate(project.id, first["id"])
    second = service.create_candidate(
        project.id,
        "# 大纲\n\n## 开头\n主角收到带血的求救信。\n\n## 中段\n第一次营救失败。\n\n## 结尾\n主角救回朋友，但失去记忆。\n",
    )

    report = service.compare_candidate(project.id, second["id"])

    assert report["summary"]["added"] == 1
    assert report["summary"]["changed"] >= 2
    assert {item["label"] for item in report["changes"]} >= {"开头", "中段", "结尾"}
    assert report["model_called"] is False
    assert report["can_apply"] is True


def test_canon_conflicts_require_a_choice_and_can_keep_project_facts(tmp_path) -> None:
    _db, projects, project, service = setup_outline_service(tmp_path)
    metadata_path = project.path / "project.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["story_requirements"] = {
        "protagonist.name": "苏荞", "world.locations": "容府、东市",
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
    candidate = service.create_candidate(
        project.id,
        "# 新大纲\n\n**方小满（冒牌千金）**住进沈府。\n\n沈府众人开始试探她。\n",
    )

    report = service.compare_candidate(project.id, candidate["id"])

    assert {item["key"] for item in report["canon_conflicts"]} >= {
        "protagonist", "primary_location",
    }
    assert report["can_apply"] is False
    with pytest.raises(ValueError, match="设定冲突"):
        service.apply_candidate(project.id, candidate["id"])
    applied = service.apply_candidate(
        project.id, candidate["id"], canon_choices={
            item["id"]: "keep_current" for item in report["canon_conflicts"]
        },
    )
    assert "苏荞" in applied["content"]
    assert "容府" in applied["content"]
    assert service.writing_readiness(project.id)["ready"] is True


def test_conflicting_candidate_can_create_independent_project(tmp_path) -> None:
    _db, projects, project, service = setup_outline_service(tmp_path)
    candidate = service.create_candidate(
        project.id,
        "# 错认鸾枝\n\n**方小满（冒牌千金）**进入沈府，决定查清错认真相。\n",
    )

    created = service.create_project_from_candidate(project.id, candidate["id"])

    assert created["id"] != project.id
    assert created["materials_need_generation"] is True
    assert service.current(created["id"])["content"].startswith("# 错认鸾枝")
    assert service.get_candidate(project.id, candidate["id"])["status"] == "pending"
    assert projects.get(project.id).path.is_dir()


def test_conflicting_current_outline_can_create_clean_project_without_changing_source(
    tmp_path,
) -> None:
    db, projects, project, service = setup_outline_service(tmp_path)
    candidate = service.create_candidate(
        project.id,
        "# 错认鸾枝\n\n**方小满（冒牌千金）**进入沈府，决定查清错认真相。\n",
    )
    service.apply_candidate(project.id, candidate["id"])
    db.create_run("source-run", project.id, "short-story", status="completed")
    metadata_path = project.path / "project.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata.update({
        "must_include": "旧人物苏荞必须出现",
        "must_avoid": "不得离开容府",
        "story_requirements": {
            "protagonist.name": "苏荞", "world.locations": "容府、东市",
        },
    })
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
    source_outline = service.current(project.id)["content"]

    assert service.writing_readiness(project.id)["ready"] is False
    created = service.create_project_from_current(project.id)

    assert created["id"] != project.id
    assert created["materials_need_generation"] is True
    assert service.current(created["id"])["content"] == source_outline
    assert service.current(project.id)["content"] == source_outline
    assert db.get_run("source-run")["project_id"] == project.id
    new_metadata = projects.get(created["id"]).metadata
    assert new_metadata["must_include"] == ""
    assert new_metadata["must_avoid"] == ""
    assert "protagonist.name" not in new_metadata["story_requirements"]


def test_selected_changes_create_new_outline_version_and_preserve_unselected_blocks(tmp_path) -> None:
    _db, _projects, project, service = setup_outline_service(tmp_path)
    initial = service.create_candidate(
        project.id,
        "# 大纲\n\n## 开头\n旧开头。\n\n## 中段\n旧中段。\n\n## 结尾\n旧结尾。\n",
    )
    service.apply_candidate(project.id, initial["id"])
    candidate = service.create_candidate(
        project.id,
        "# 大纲\n\n## 开头\n新开头。\n\n## 中段\n新中段。\n\n## 结尾\n新结尾。\n",
    )
    report = service.compare_candidate(project.id, candidate["id"])
    middle = next(item for item in report["changes"] if item["label"] == "中段")

    applied = service.apply_candidate(
        project.id, candidate["id"], change_ids=[middle["id"]],
        expected_revision=report["state_revision"],
    )

    assert "旧开头" in applied["content"]
    assert "新中段" in applied["content"]
    assert "旧结尾" in applied["content"]
    assert applied["outline_version"] == 2
    assert (project.path / "plot" / "outline.md").read_text(encoding="utf-8") == applied["content"]


def test_whole_outline_requires_explicit_confirmation_after_manuscript_exists(tmp_path) -> None:
    _db, _projects, project, service = setup_outline_service(tmp_path)
    initial = service.create_candidate(project.id, "# 大纲\n\n旧剧情。\n")
    service.apply_candidate(project.id, initial["id"])
    manuscript = project.path / "manuscript" / "story.md"
    manuscript.write_text("# 正文\n\n已经写好的正文。\n", encoding="utf-8")
    candidate = service.create_candidate(project.id, "# 大纲\n\n新剧情。\n")

    with pytest.raises(ValueError, match="已有正文"):
        service.apply_candidate(project.id, candidate["id"])

    applied = service.apply_candidate(
        project.id, candidate["id"], allow_full_with_manuscript=True,
    )
    assert "新剧情" in applied["content"]
    assert manuscript.read_text(encoding="utf-8") == "# 正文\n\n已经写好的正文。\n"


def test_locked_fact_removal_blocks_outline_application(tmp_path) -> None:
    db, _projects, project, service = setup_outline_service(tmp_path)
    initial = service.create_candidate(project.id, "# 大纲\n\n林舟必须活到结局。\n")
    service.apply_candidate(project.id, initial["id"])
    with db.connect() as connection:
        row = connection.execute(
            "SELECT revision,state_json FROM story_states WHERE project_id=?", (project.id,),
        ).fetchone()
        import json
        data = json.loads(row["state_json"])
        data["locked_facts"] = [{"key": "ending", "value": "林舟必须活到结局"}]
        connection.execute(
            "UPDATE story_states SET state_json=? WHERE project_id=?",
            (json.dumps(data, ensure_ascii=False), project.id),
        )
    candidate = service.create_candidate(project.id, "# 大纲\n\n林舟在中段消失。\n")

    with pytest.raises(ValueError, match="锁定设定"):
        service.apply_candidate(project.id, candidate["id"])


def test_restoring_history_creates_a_new_version_instead_of_erasing_history(tmp_path) -> None:
    _db, _projects, project, service = setup_outline_service(tmp_path)
    first = service.create_candidate(project.id, "# 第一版\n")
    service.apply_candidate(project.id, first["id"])
    second = service.create_candidate(project.id, "# 第二版\n")
    service.apply_candidate(project.id, second["id"])

    restored = service.restore(project.id, outline_version=1)
    history = service.history(project.id)

    assert restored["content"] == "# 第一版\n"
    assert restored["outline_version"] == 3
    assert [item["outline_version"] for item in history] == [1, 2, 3]
    assert history[-1]["source"] == "restored"


def test_candidate_reject_keeps_history_but_removes_it_from_active_list(tmp_path) -> None:
    _db, _projects, project, service = setup_outline_service(tmp_path)
    candidate = service.create_candidate(project.id, "# 不采用\n")

    rejected = service.reject_candidate(project.id, candidate["id"], "方向不合适")

    assert rejected["status"] == "rejected"
    assert service.list_candidates(project.id) == []


def test_outline_length_is_bounded(tmp_path) -> None:
    _db, _projects, project, service = setup_outline_service(tmp_path)

    with pytest.raises(ValueError, match="100,000"):
        service.create_candidate(project.id, "大" * 100_001)


def test_applying_outline_marks_only_outline_derived_artifacts_stale(tmp_path) -> None:
    db, projects, project, service = setup_outline_service(tmp_path)
    learning = LearningSystem(
        db, ReferenceLibrary(db, tmp_path / "references"), projects, gateway=None,
    )
    learning.save_artifact(project.id, "scene_briefs", {"briefs": []})
    learning.save_artifact(project.id, "short_causal_chain", {"cycles": []})
    learning.save_artifact(project.id, "voice_profiles", {"人物甲": {"rules": "少说话"}})
    manuscript = project.path / "manuscript" / "story.md"
    manuscript.write_text("# 正文\n\n已经写好的内容。\n", encoding="utf-8")
    before = manuscript.read_bytes()
    candidate = service.create_candidate(project.id, "# 新大纲\n")

    service.apply_candidate(
        project.id, candidate["id"], allow_full_with_manuscript=True,
    )

    assert learning.get_artifact(project.id, "scene_briefs")["status"] == "stale"
    assert learning.get_artifact(project.id, "short_causal_chain")["status"] == "stale"
    assert learning.get_artifact(project.id, "voice_profiles")["status"] == "active"
    assert manuscript.read_bytes() == before
    saved = json.loads((project.path / "learning" / "scene_briefs.json").read_text(encoding="utf-8"))
    assert saved["status"] == "stale"
