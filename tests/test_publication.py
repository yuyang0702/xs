import hashlib
import json

import pytest

from novel_flywheel.db import Database
from novel_flywheel.projects import ProjectCreate, ProjectStore
from novel_flywheel.publication import build_zhihu_package, preview_zhihu_package


def project_for_export(tmp_path):
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="归来", mode="short", genre="悬疑", premise="朋友死而复生。", target_words=8000,
    ))
    return store.apply_platform_profile(project.id, "zhihu-salt-short")


def metadata(text):
    return {
        "title": "归来", "alternate_titles": ["死去的朋友回来了"],
        "selling_point": "葬礼之后，死者亲自敲响我的门。",
        "introduction": "我想复活朋友，却发现回来的人知道我埋藏的秘密。",
        "content_type": "悬疑", "audience": "喜欢反转悬疑的读者",
        "expected_manuscript_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def test_preview_requires_formal_manuscript_and_profile(tmp_path) -> None:
    project = project_for_export(tmp_path)
    with pytest.raises(ValueError, match="正式稿"):
        preview_zhihu_package(project)

    project.metadata["platform_profile_id"] = None
    with pytest.raises(ValueError, match="知乎盐选短篇"):
        preview_zhihu_package(project)


def test_build_requires_clear_submission_metadata(tmp_path) -> None:
    project = project_for_export(tmp_path)
    path = project.path / "manuscript" / "story.md"
    path.write_text("正文", encoding="utf-8")

    with pytest.raises(ValueError, match="一句话卖点"):
        build_zhihu_package(project, {"title": "归来", "introduction": "简介"})


def test_build_rejects_changed_manuscript_after_preview(tmp_path) -> None:
    project = project_for_export(tmp_path)
    path = project.path / "manuscript" / "story.md"
    path.write_text("正文", encoding="utf-8")
    payload = metadata("正文")
    path.write_text("正文已修改", encoding="utf-8")

    with pytest.raises(ValueError, match="正文已经发生变化"):
        build_zhihu_package(project, payload)


def test_build_creates_versioned_packages_without_changing_manuscript(tmp_path) -> None:
    project = project_for_export(tmp_path)
    manuscript = project.path / "manuscript" / "story.md"
    text = "正式正文" * 1800
    manuscript.write_text(text, encoding="utf-8")
    run_output = project.path / "runs" / "done" / "outputs"
    run_output.mkdir(parents=True)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    (run_output / "quality-report.json").write_text(json.dumps({
        "status": "passed",
        "terminal_reviewed_hash": digest,
        "scoring_profile_id": "zhihu-short-v2",
        "review": {"score": 88, "scoring_profile_id": "zhihu-short-v2"},
    }, ensure_ascii=False), encoding="utf-8")

    first = build_zhihu_package(project, metadata(text))
    second = build_zhihu_package(project, metadata(text))

    assert first["version"] == "v001"
    assert second["version"] == "v002"
    assert (project.path / "publication" / "zhihu" / "v001" / "manuscript.md").read_text(encoding="utf-8") == text
    exported = json.loads((project.path / "publication" / "zhihu" / "v001" / "metadata.json").read_text(encoding="utf-8"))
    assert exported["manuscript_hash"] == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert manuscript.read_text(encoding="utf-8") == text


def test_package_authority_rejects_passed_review_for_a_different_manuscript(tmp_path) -> None:
    project = project_for_export(tmp_path)
    manuscript = project.path / "manuscript" / "story.md"
    manuscript.write_text("当前正式正文", encoding="utf-8")
    run_output = project.path / "runs" / "done" / "outputs"
    run_output.mkdir(parents=True)
    (run_output / "quality-report.json").write_text(json.dumps({
        "status": "passed",
        "terminal_reviewed_hash": hashlib.sha256("旧正文".encode("utf-8")).hexdigest(),
        "scoring_profile_id": "zhihu-short-v2",
    }, ensure_ascii=False), encoding="utf-8")

    preview = preview_zhihu_package(project)

    assert preview["ready"] is False
    assert preview["publication_authority"]["can_generate_package"] is False
    assert any(
        "不是当前正式稿" in reason
        for reason in preview["publication_authority"]["blocking_reasons"]
    )
    with pytest.raises(ValueError, match="不是当前正式稿"):
        build_zhihu_package(project, metadata("当前正式正文"))
