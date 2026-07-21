import pytest

from novel_flywheel.db import Database
from novel_flywheel.memory import StoryMemory
from novel_flywheel.projects import ProjectCreate, ProjectStore
from novel_flywheel.tools import StoryToolbox


def make_toolbox(tmp_path):
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Long", mode="long", genre="fantasy", premise="A key.", target_words=100000,
    ))
    memory = StoryMemory(db)
    memory.index_chapter(project.id, "chapter-01", 1, "The brass key opened the observatory.", "key found")
    (project.path / "chapters" / "chapter-01.md").write_text("Secret chapter text", encoding="utf-8")
    return StoryToolbox(project, memory)


def test_toolbox_searches_and_reads_only_project_chapters(tmp_path) -> None:
    toolbox = make_toolbox(tmp_path)
    result = toolbox.execute("search_chapters", {"query": "brass key", "limit": 2})
    assert "brass key" in result["items"][0]["excerpt"].lower()
    assert toolbox.execute("read_chapter", {"chapter_number": 1, "start": 0, "length": 20})["text"] == "Secret chapter text"


def test_toolbox_rejects_unknown_tools_paths_and_oversized_reads(tmp_path) -> None:
    toolbox = make_toolbox(tmp_path)
    with pytest.raises(ValueError, match="Unknown tool"):
        toolbox.execute("read_file", {"path": "../secret"})
    with pytest.raises(ValueError):
        toolbox.execute("read_chapter", {"chapter_number": 1, "path": "../secret"})
    with pytest.raises(ValueError):
        toolbox.execute("read_chapter", {"chapter_number": 1, "length": 9000})
