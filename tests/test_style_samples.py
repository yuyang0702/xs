import json
from types import SimpleNamespace

import pytest

from novel_flywheel.projects import Project
from novel_flywheel.style_samples import StyleSampleService


class Gateway:
    def __init__(self, output=None, error=None):
        self.output = output
        self.error = error
        self.calls = []

    async def complete(self, role, system, user, max_output_tokens=None):
        self.calls.append((role, system, user, max_output_tokens))
        if self.error:
            raise self.error
        return SimpleNamespace(text=json.dumps(self.output, ensure_ascii=False), receipt={})


def project(tmp_path):
    root = tmp_path / "book"
    root.mkdir()
    return Project("p1", "Book", "short", root, {"genre": "悬疑", "tone": "克制"})


@pytest.mark.asyncio
async def test_analyze_stores_source_and_updates_only_managed_profile_block(tmp_path):
    item = project(tmp_path)
    (item.path / "style-profile.md").write_text("# 基础风格\n\n保留我。\n", encoding="utf-8")
    profile = {
        "summary": "冷静但不疏离",
        "sentence_rhythm": ["长短句交替"],
        "dialogue": ["短对白推动冲突"],
        "narrative_distance": ["贴近人物即时感受"],
        "characterization": ["用动作和停顿表现情绪"],
        "diction": ["日常具体词汇"],
        "avoid": ["抽象主题总结"],
    }
    service = StyleSampleService(Gateway(profile))

    result = await service.analyze(item, "锅里的水开了。" * 40, "sample.txt")

    assert result["configured"] is True
    assert (item.path / "style-samples" / "reference.txt").is_file()
    text = (item.path / "style-profile.md").read_text(encoding="utf-8")
    assert "保留我" in text
    assert "冷静但不疏离" in text
    assert "用动作和停顿表现情绪" in text


@pytest.mark.asyncio
async def test_failed_analysis_preserves_existing_files(tmp_path):
    item = project(tmp_path)
    source = item.path / "style-samples" / "reference.txt"
    source.parent.mkdir()
    source.write_text("old source", encoding="utf-8")
    profile = item.path / "style-profile.md"
    profile.write_text("old profile", encoding="utf-8")

    with pytest.raises(RuntimeError):
        await StyleSampleService(Gateway(error=RuntimeError("offline"))).analyze(
            item, "新的范文内容。" * 40, "new.txt"
        )

    assert source.read_text(encoding="utf-8") == "old source"
    assert profile.read_text(encoding="utf-8") == "old profile"


@pytest.mark.asyncio
async def test_rejects_too_short_sample_before_model_call(tmp_path):
    gateway = Gateway({})
    with pytest.raises(ValueError, match="至少"):
        await StyleSampleService(gateway).analyze(project(tmp_path), "太短", "x.txt")
    assert gateway.calls == []


def test_delete_removes_sample_and_managed_block_only(tmp_path):
    item = project(tmp_path)
    folder = item.path / "style-samples"
    folder.mkdir()
    (folder / "reference.txt").write_text("sample", encoding="utf-8")
    (item.path / "style-profile.md").write_text(
        "# 基础风格\n\n保留我。\n\n<!-- STYLE_SAMPLE_START -->\n学习内容\n<!-- STYLE_SAMPLE_END -->\n",
        encoding="utf-8",
    )

    result = StyleSampleService(Gateway()).delete(item)

    assert result["configured"] is False
    assert not folder.exists()
    assert (item.path / "style-profile.md").read_text(encoding="utf-8").strip() == "# 基础风格\n\n保留我。"
