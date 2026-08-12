import json
from types import SimpleNamespace

import pytest

import novel_flywheel.style_samples as style_samples_module
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


class SequenceGateway(Gateway):
    def __init__(self, outputs):
        super().__init__()
        self.outputs = iter(outputs)

    async def complete(self, role, system, user, max_output_tokens=None):
        self.calls.append((role, system, user, max_output_tokens))
        return SimpleNamespace(text=next(self.outputs), receipt={})


def project(tmp_path):
    root = tmp_path / "book"
    root.mkdir()
    return Project("p1", "Book", "short", root, {"genre": "悬疑", "tone": "克制"})


@pytest.mark.asyncio
async def test_analyze_stores_source_and_updates_only_managed_profile_block(tmp_path):
    item = project(tmp_path)
    (item.path / "style-profile.md").write_text("# 基础风格\n\n保留我。\n", encoding="utf-8")
    learning = item.path / "learning"
    learning.mkdir()
    (learning / "prose_baseline.json").write_text(json.dumps({
        "status": "active", "data": {"dialogue": ["只在运行时使用的基础文笔。"]},
    }, ensure_ascii=False), encoding="utf-8")
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
    assert "只在运行时使用的基础文笔" not in text


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
async def test_style_outputs_roll_back_together_when_second_write_fails(
    tmp_path, monkeypatch,
):
    item = project(tmp_path)
    folder = item.path / "style-samples"
    folder.mkdir()
    source = folder / "reference.txt"
    stored_profile = folder / "profile.json"
    rendered_profile = item.path / "style-profile.md"
    source.write_text("old source", encoding="utf-8")
    stored_profile.write_text('{"summary":"old"}', encoding="utf-8")
    rendered_profile.write_text("old rendered profile", encoding="utf-8")
    original_bytes = {
        path: path.read_bytes()
        for path in (source, stored_profile, rendered_profile)
    }
    profile = {
        "summary": "restrained",
        "sentence_rhythm": ["vary sentence length"],
        "dialogue": ["use short dialogue"],
        "narrative_distance": ["stay close to the viewpoint"],
        "characterization": ["show emotion through action"],
        "diction": ["use concrete words"],
        "avoid": ["avoid abstract summaries"],
    }
    original_atomic_write = style_samples_module.atomic_write

    def fail_on_profile_json(path, content, *args, **kwargs):
        if path.name == "profile.json":
            raise OSError("injected profile write failure")
        return original_atomic_write(path, content, *args, **kwargs)

    monkeypatch.setattr(style_samples_module, "atomic_write", fail_on_profile_json)

    with pytest.raises(OSError, match="injected profile write failure"):
        await StyleSampleService(Gateway(profile)).analyze(
            item, "A representative prose sample. " * 20, "sample.txt",
        )

    for path, expected in original_bytes.items():
        assert path.read_bytes() == expected
    snapshots = item.path / "snapshots"
    assert not snapshots.exists() or list(snapshots.iterdir()) == []


@pytest.mark.asyncio
async def test_analyze_repairs_non_json_model_output_once(tmp_path):
    profile = {
        "summary": "restrained",
        "sentence_rhythm": ["vary sentence length"],
        "dialogue": ["use short dialogue"],
        "narrative_distance": ["stay close to the viewpoint"],
        "characterization": ["show emotion through action"],
        "diction": ["use concrete words"],
        "avoid": ["avoid abstract summaries"],
    }
    gateway = SequenceGateway(["Here is the analysis, not JSON.", json.dumps(profile)])

    result = await StyleSampleService(gateway).analyze(
        project(tmp_path), "A representative prose sample. " * 20, "sample.txt",
    )

    assert result["configured"] is True
    assert result["profile"]["summary"] == "restrained"
    assert len(gateway.calls) == 2


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


def test_delete_rolls_back_folder_when_profile_write_fails(tmp_path, monkeypatch):
    item = project(tmp_path)
    folder = item.path / "style-samples"
    folder.mkdir()
    source = folder / "reference.txt"
    stored_profile = folder / "profile.json"
    rendered_profile = item.path / "style-profile.md"
    source.write_text("sample", encoding="utf-8")
    stored_profile.write_text('{"summary":"old"}', encoding="utf-8")
    rendered_profile.write_text(
        "# Base\n\nKeep me.\n\n"
        "<!-- STYLE_SAMPLE_START -->\nManaged\n<!-- STYLE_SAMPLE_END -->\n",
        encoding="utf-8",
    )
    original_bytes = {
        path: path.read_bytes()
        for path in (source, stored_profile, rendered_profile)
    }

    def fail_profile_write(path, content, *args, **kwargs):
        raise OSError("injected managed profile delete failure")

    monkeypatch.setattr(style_samples_module, "atomic_write", fail_profile_write)

    with pytest.raises(OSError, match="injected managed profile delete failure"):
        StyleSampleService(Gateway()).delete(item)

    for path, expected in original_bytes.items():
        assert path.read_bytes() == expected
    assert sorted(path.name for path in folder.iterdir()) == [
        "profile.json", "reference.txt",
    ]
