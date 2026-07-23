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
