import json

import pytest

from novel_flywheel.db import Database
from novel_flywheel.story_state import (
    STORY_STATE_SCHEMA,
    StaleStoryState,
    StoryStateStore,
    authoritative_fact_snapshot,
    migrate_story_state_data,
    validate_locked_facts,
)


def make_project(db, root, project_id="book"):
    root.mkdir()
    (root / "memory").mkdir()
    (root / "manuscript").mkdir()
    (root / "memory" / "canon.json").write_text(json.dumps({
        "facts": [{"fact_key": "ending", "value": "The heroine leaves."}],
        "state": {"heroine": {"location": "station"}},
    }), encoding="utf-8")
    (root / "manuscript" / "story.md").write_text("Existing manuscript", encoding="utf-8")
    db.save_project(project_id, project_id, "short", root)


def test_authoritative_fact_snapshot_is_deep_and_excludes_runtime_fields() -> None:
    state = {
        "locked_facts": [{"key": "ending", "value": {"place": "station"}}],
        "confirmed_facts": [{"key": "name", "value": "Lin"}],
        "world_rules": ["Doors open once."],
        "character_states": {"Lin": {"location": "station"}},
        "timeline_events": [{"when": "dawn", "event": "Lin leaves"}],
        "issue_ledger": [{"issue_id": "runtime-only"}],
        "manuscript_revision": 9,
    }

    snapshot = authoritative_fact_snapshot(state)
    snapshot["locked_facts"][0]["value"]["place"] = "harbor"

    assert list(snapshot) == [
        "locked_facts",
        "confirmed_facts",
        "world_rules",
        "character_states",
        "timeline_events",
        "narrative_graph",
        "narrative_rule_profile",
    ]
    assert state["locked_facts"][0]["value"]["place"] == "station"


def test_story_state_migrates_existing_project_without_rewriting_files(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    project = tmp_path / "book"
    make_project(db, project)
    store = StoryStateStore(db)

    before = (project / "memory" / "canon.json").read_bytes()
    state = store.ensure("book", project)
    again = store.ensure("book", project)

    assert state.revision == 1
    assert state.data["confirmed_facts"][0]["key"] == "ending"
    assert state.data["character_states"]["heroine"]["location"] == "station"
    assert state.data["manuscript_revision"] == 1
    assert again == state
    assert (project / "memory" / "canon.json").read_bytes() == before


def test_empty_initial_state_imports_files_generated_after_project_creation(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    root = tmp_path / "book"
    (root / "memory").mkdir(parents=True)
    (root / "continuity").mkdir()
    (root / "plot").mkdir()
    (root / "manuscript").mkdir()
    (root / "characters").mkdir()
    (root / "memory" / "canon.json").write_text('{"facts": []}', encoding="utf-8")
    (root / "continuity" / "locks.json").write_text('{"locks": []}', encoding="utf-8")
    (root / "continuity" / "state.md").write_text("# State\n", encoding="utf-8")
    (root / "plot" / "timeline.md").write_text("# Timeline\n", encoding="utf-8")
    (root / "project.json").write_text('{"story_requirements": {}}', encoding="utf-8")
    db.save_project("book", "Book", "short", root)
    store = StoryStateStore(db)
    assert store.ensure("book", root).data["locked_facts"] == []

    (root / "project.json").write_text(json.dumps({
        "story_requirements": {
            "ending": "女主归隐山野",
            "world.rules": "穿越不可逆",
        },
    }, ensure_ascii=False), encoding="utf-8")
    (root / "characters" / "hero.md").write_text(
        '---\nname: "林知晚"\nrole: protagonist\nstatus: alive\narc: 选择自由\n---\n',
        encoding="utf-8",
    )

    state = store.ensure("book", root)

    assert state.revision == 1
    assert state.data["world_rules"] == ["穿越不可逆"]
    assert state.data["character_states"]["林知晚"]["role"] == "protagonist"
    assert any(item["key"] == "ending" for item in state.data["locked_facts"])


def test_story_states_are_isolated_by_project(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    make_project(db, tmp_path / "one", "one")
    make_project(db, tmp_path / "two", "two")
    store = StoryStateStore(db)

    one = store.ensure("one", tmp_path / "one")
    two = store.ensure("two", tmp_path / "two")

    assert one.project_id == "one"
    assert two.project_id == "two"
    assert store.get("one").project_id == "one"


def test_stale_candidate_cannot_overwrite_newer_story_state(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    make_project(db, tmp_path / "book")
    store = StoryStateStore(db)
    initial = store.ensure("book", tmp_path / "book")
    first = store.create_candidate("book", "run-1", initial.revision, "polish", "hash-1")
    stale = store.create_candidate("book", "run-2", initial.revision, "polish", "hash-2")

    committed = store.commit(first.id, initial.revision, {**initial.data, "manuscript_revision": 2})

    assert committed.revision == 2
    with pytest.raises(StaleStoryState):
        store.commit(stale.id, initial.revision, initial.data)
    assert store.get_candidate(stale.id).status == "rejected"
    assert len(store.history("book")) == 2


def test_candidate_rejection_preserves_authoritative_state(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    make_project(db, tmp_path / "book")
    store = StoryStateStore(db)
    initial = store.ensure("book", tmp_path / "book")
    candidate = store.create_candidate("book", "run", initial.revision, "draft", "hash")

    store.reject(candidate.id, "locked fact changed")

    assert store.get("book") == initial
    assert store.get_candidate(candidate.id).status == "rejected"
    assert store.get_candidate(candidate.id).reason == "locked fact changed"


def test_imports_project_and_continuity_locks_and_detects_literal_removal(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    project = tmp_path / "book"
    make_project(db, project)
    (project / "continuity").mkdir()
    (project / "continuity" / "locks.json").write_text(json.dumps({
        "locks": [{"key": "ending", "value": "The heroine leaves."}],
    }), encoding="utf-8")
    (project / "project.json").write_text(json.dumps({
        "story_requirements": {"protagonist.name": "Lin", "ending": "The heroine leaves."},
    }), encoding="utf-8")

    state = StoryStateStore(db).ensure("book", project)

    assert {item["key"] for item in state.data["locked_facts"]} == {
        "ending", "protagonist.name",
    }
    assert validate_locked_facts(
        "Lin watches. The heroine leaves.", "Lin watches.", state.data,
    ) == ["locked fact removed: ending"]


def test_initial_story_state_exposes_project_world_rules(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    project = tmp_path / "book"
    make_project(db, project)
    (project / "project.json").write_text(json.dumps({
        "story_requirements": {"world.rules": "Doors only open once."},
    }), encoding="utf-8")
    store = StoryStateStore(db)

    state = store.ensure("book", project)

    assert state.data["world_rules"] == ["Doors only open once."]


def test_existing_story_state_backfills_visible_project_material_once(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    project = tmp_path / "book"
    make_project(db, project)
    (project / "project.json").write_text(json.dumps({
        "story_requirements": {"world.rules": "Doors only open once."},
    }), encoding="utf-8")
    (project / "memory" / "canon.json").write_text(json.dumps({
        "facts": ["Lin knows the truth."],
    }), encoding="utf-8")
    (project / "continuity").mkdir()
    (project / "continuity" / "state.md").write_text(
        "---\ncharacter-state:\n  - name: Lin\n    location: station\n---\n\n"
        "## Key State\n\n- Mei: waiting at home\n", encoding="utf-8",
    )
    (project / "plot").mkdir()
    (project / "plot" / "timeline.md").write_text(
        "# Timeline\n\n| When | Event |\n|---|---|\n| Dawn | Lin leaves |\n", encoding="utf-8",
    )
    store = StoryStateStore(db)
    initial = store.ensure("book", project)
    candidate = store.create_candidate("book", "run", initial.revision, "polish", "hash")
    legacy = {key: value for key, value in initial.data.items() if key != "story_state_schema"}
    store.commit(candidate.id, initial.revision, {**legacy, "world_rules": []})

    state = store.ensure("book", project)

    assert state.revision == 2
    assert state.data["world_rules"] == ["Doors only open once."]
    assert state.data["confirmed_facts"][0]["value"] == "Lin knows the truth."
    assert state.data["character_states"]["Lin"]["location"] == "station"
    assert state.data["character_states"]["Mei"]["state"] == "waiting at home"
    assert state.data["timeline_events"] == [{"When": "Dawn", "Event": "Lin leaves"}]
    assert state.data["story_state_schema"] == STORY_STATE_SCHEMA
    assert state.data["narrative_graph"]["version"] == 1


def test_story_state_v3_migration_is_idempotent_and_preserves_legacy_authority() -> None:
    legacy = {
        "story_state_schema": 2,
        "locked_facts": [{"key": "ending", "value": "归隐"}],
        "confirmed_facts": [{"key": "identity", "value": "花穗"}],
        "world_rules": ["身份不能凭空改变"],
        "character_states": {"花穗": {"location": "沈府"}},
        "timeline_events": [{"when": "午后", "event": "公开坦白"}],
    }

    migrated = migrate_story_state_data(legacy)
    again = migrate_story_state_data(migrated)

    assert migrated == again
    assert migrated["story_state_schema"] == STORY_STATE_SCHEMA
    assert migrated["locked_facts"] == legacy["locked_facts"]
    assert migrated["character_states"] == legacy["character_states"]
    assert migrated["narrative_graph"] == {
        "version": 1, "claims": [], "identities": [],
        "relationships": [], "promises": [],
    }


def test_story_state_commit_rejects_identity_knowledge_regression(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    project = tmp_path / "book"
    make_project(db, project)
    store = StoryStateStore(db)
    state = store.ensure("book", project)
    candidate = store.create_candidate(
        "book", "run", state.revision, "planning", "candidate-hash",
    )
    graph = {
        "version": 1,
        "claims": [
            {
                "claim_id": "confession", "subject": "花穗",
                "predicate": "identity.actual", "value": "花穗",
                "perspective": "public", "status": "known",
                "transition": "reveal", "authority": "formal",
                "event_order": 4, "evidence": "公开坦白",
            },
            {
                "claim_id": "later-question", "subject": "花穗",
                "predicate": "identity.actual", "value": None,
                "perspective": "public", "status": "unknown",
                "transition": "question", "authority": "candidate",
                "event_order": 6, "evidence": "身份已经问不出来",
            },
        ],
        "identities": [], "relationships": [], "promises": [],
    }

    with pytest.raises(ValueError, match="knowledge_regression"):
        store.commit(candidate.id, state.revision, {
            **state.data, "narrative_graph": graph,
        })

    assert store.get("book") == state
    assert store.get_candidate(candidate.id).status == "rejected"
