import json
from pathlib import Path

from novel_flywheel.style_context import character_fingerprints, ensure_style_profile


def test_style_profile_is_created_once_from_project_metadata(tmp_path: Path) -> None:
    project = type("Project", (), {
        "path": tmp_path,
        "metadata": {"genre": "悬疑", "tone": "克制冷峻", "perspective": "第三人称限知"},
    })()

    first = ensure_style_profile(project)
    (tmp_path / "style-profile.md").write_text(first + "\n自定义规则", encoding="utf-8")

    assert "悬疑" in first
    assert "克制冷峻" in first
    assert ensure_style_profile(project).endswith("自定义规则")


def test_character_fingerprints_only_include_named_characters(tmp_path: Path) -> None:
    folder = tmp_path / "characters"
    folder.mkdir()
    (folder / "chen.md").write_text("# 陈东\n\n说话习惯：短句，不解释。\n称呼：叫妹妹小雨。", encoding="utf-8")
    (folder / "li.md").write_text("# 李明\n\n说话习惯：文绉绉。", encoding="utf-8")

    result = character_fingerprints(tmp_path, "陈东推开门。")

    assert "陈东" in result
    assert "短句" in result
    assert "李明" not in result


def test_migrated_legacy_sample_is_not_injected_twice(tmp_path: Path) -> None:
    project = type("Project", (), {"path": tmp_path, "metadata": {}})()
    (tmp_path / "style-profile.md").write_text(
        "# 基础风格\n\n保留。\n\n<!-- STYLE_SAMPLE_START -->\n旧范文规则\n<!-- STYLE_SAMPLE_END -->\n",
        encoding="utf-8",
    )
    learning = tmp_path / "learning"
    learning.mkdir()
    (learning / "prose_baseline.json").write_text(json.dumps({
        "status": "active", "data": {"source": "legacy_style_sample", "dialogue": ["旧范文规则"]},
    }, ensure_ascii=False), encoding="utf-8")

    result = ensure_style_profile(project)

    assert "保留" in result
    assert "旧范文规则" not in result
    assert "旧范文规则" in (tmp_path / "style-profile.md").read_text(encoding="utf-8")
