from novel_flywheel.db import Database
from novel_flywheel.memory import StoryMemory


def test_memory_retrieves_relevant_chapters_without_loading_whole_book(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    memory = StoryMemory(db)
    memory.index_chapter("book", "ch-1", 1, "The brass key opened the observatory.", "key found")
    memory.index_chapter("book", "ch-2", 2, "A storm closed the mountain road.", "road closed")

    context = memory.context("book", "brass key", limit=1)

    assert [item["chapter_id"] for item in context["relevant_chapters"]] == ["ch-1"]
    assert "brass key" in context["relevant_chapters"][0]["excerpt"].lower()
    assert len(context["relevant_chapters"][0]["excerpt"]) <= 1200
    assert "storm" not in str(context)


def test_confirmed_canon_fact_cannot_be_silently_overwritten(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    memory = StoryMemory(db)
    memory.add_fact("book", "hero.location", "Beijing", confirmed=True, source="ch-1")
    memory.add_fact("book", "hero.location", "Shanghai", confirmed=True, source="ch-2")
    facts = memory.context("book", "hero", limit=1)["canon"]
    assert facts == [{"fact_key": "hero.location", "value": "Beijing", "source": "ch-1"}]


def test_context_includes_recent_state_and_open_drift(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    memory = StoryMemory(db)
    memory.save_state("book", "ch-9", {"hero": {"injury": "left arm"}})
    memory.record_drift("book", "character", 70, "Hero forgot the injury")
    context = memory.context("book", "injury")
    assert context["recent_state"]["hero"]["injury"] == "left arm"
    assert context["drift"][0]["score"] == 70
