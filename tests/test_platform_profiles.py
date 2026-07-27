from novel_flywheel.db import Database
from novel_flywheel.platform_profiles import resolve_platform_profile
from novel_flywheel.projects import ProjectCreate, ProjectStore


def make_project(tmp_path, mode="short"):
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="测试作品", mode=mode, genre="悬疑", premise="朋友死而复生。", target_words=8000,
    ))
    return store, project


def test_zhihu_profile_separates_rules_from_market_advice(tmp_path) -> None:
    _, project = make_project(tmp_path)
    profile = resolve_platform_profile("zhihu-salt-short", project, None)

    assert profile["name"] == "知乎盐选短篇创作配置"
    assert profile["hard_rules"]
    assert profile["market_advice"] == []
    assert "没有可用" in profile["market_note"]


def test_project_profile_preview_and_apply_never_write_manuscript(tmp_path) -> None:
    store, project = make_project(tmp_path)
    manuscript = project.path / "manuscript" / "story.md"
    manuscript.write_text("正式正文保持不变", encoding="utf-8")

    preview = store.preview_platform_profile(project.id, "zhihu-salt-short")
    changed = store.apply_platform_profile(project.id, "zhihu-salt-short")

    assert preview["will_change_manuscript"] is False
    assert changed.metadata["platform_profile_id"] == "zhihu-salt-short"
    assert manuscript.read_text(encoding="utf-8") == "正式正文保持不变"
    constraints = store.load_constraints(project.id)
    assert "PLATFORM HARD RULES" in constraints
    assert "MARKET ADVICE" in constraints


def test_zhihu_short_profile_rejects_long_project(tmp_path) -> None:
    store, project = make_project(tmp_path, mode="long")

    try:
        store.preview_platform_profile(project.id, "zhihu-salt-short")
    except ValueError as exc:
        assert "短篇" in str(exc)
    else:
        raise AssertionError("long project should not accept the short-story profile")
