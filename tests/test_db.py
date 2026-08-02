import sqlite3
from concurrent.futures import ThreadPoolExecutor

from novel_flywheel.db import Database


def test_story_state_schema_upgrade_backs_up_existing_database_once(tmp_path) -> None:
    path = tmp_path / "app.db"
    legacy = Database(path)
    legacy.migrate()
    with legacy.connect() as connection:
        connection.execute("DROP TABLE story_candidates")
        connection.execute("DROP TABLE story_state_history")
        connection.execute("DROP TABLE story_states")

    legacy.migrate()
    backup = tmp_path / "app.pre-story-state.db"

    assert backup.is_file()
    before = backup.stat().st_mtime_ns
    legacy.migrate()
    assert backup.stat().st_mtime_ns == before


def test_database_creates_foundation_tables(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    assert {
        "providers", "models", "role_bindings", "schema_version", "run_events",
        "reference_sources", "reference_versions", "reference_analyses",
        "quality_reference_groups",
    } <= db.table_names()

    db.migrate()
    assert {
        "reference_sources", "reference_versions", "reference_analyses",
        "quality_reference_groups",
    } <= db.table_names()


def test_reference_metadata_migration_is_idempotent(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.migrate()
    with db.connect() as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(reference_sources)")}
    assert {"platform", "content_type", "project_id"} <= columns


def test_model_output_observation_migration_is_idempotent(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.migrate()

    assert "model_output_observations" in db.table_names()
    db.save_model_output_observation(
        provider_id="provider", model_id="model", route_fingerprint="route",
        execution_mode="plain", requested_max_output_tokens=16000,
        actual_output_tokens=4000, visible_characters=5000,
        finish_reason="max_tokens", transport_complete=True,
    )
    db.save_model_output_observation(
        provider_id="provider", model_id="model", route_fingerprint="route",
        execution_mode="plain", requested_max_output_tokens=20000,
        actual_output_tokens=4100, visible_characters=5100,
        finish_reason="max_tokens", transport_complete=True,
    )

    profile = db.model_output_profile("provider", "model", "route", "plain")
    assert profile["samples"] == 2
    assert 4100 <= profile["suspected_stable_output_tokens"] <= 5000
    assert db.latest_model_output_profile("provider", "model")[
        "suspected_stable_output_tokens"
    ] == profile["suspected_stable_output_tokens"]


def test_skill_execution_context_migration_is_idempotent(tmp_path) -> None:
    path = tmp_path / "app.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE skill_executions("
            "id TEXT PRIMARY KEY, project_id TEXT NOT NULL, skill_name TEXT NOT NULL, "
            "content_hash TEXT NOT NULL, status TEXT NOT NULL, error TEXT, "
            "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )

    db = Database(path)
    db.migrate()
    db.migrate()

    with db.connect() as connection:
        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(skill_executions)")
        }
    assert "context_hash" in columns


def test_run_events_are_ordered_and_active_runs_can_be_interrupted(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_project("book", "Book", "long", tmp_path / "book")
    db.create_run("run", "book", "long-chapter", status="queued")
    db.add_run_event("run", "info", "queued", "任务已排队", stage="queue")
    db.add_run_event("run", "success", "stage_completed", "规划完成", stage="planning",
                     metadata={"model": "deepseek"})

    events = db.list_run_events("run")
    assert [item["event_type"] for item in events] == ["queued", "stage_completed"]
    assert events[1]["metadata"] == {"model": "deepseek"}

    assert db.interrupt_active_runs() == 1
    assert db.get_run("run")["status"] == "interrupted"


def test_only_one_run_can_claim_the_same_project(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_project("book", "Book", "short", tmp_path / "book")

    with ThreadPoolExecutor(max_workers=4) as pool:
        accepted = list(pool.map(
            lambda index: db.create_run_if_idle(
                f"run-{index}", "book", "short-story", status="queued",
            ),
            range(4),
        ))

    assert accepted.count(True) == 1
    assert len(db.list_runs("book")) == 1


def test_database_provider_round_trip_omits_secrets(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_provider(
        provider_id="relay",
        name="Relay",
        protocol="openai-chat",
        base_url="https://relay.test/v1",
        auth_type="bearer",
        timeout_seconds=180,
        extra_headers={"X-Channel": "novel"},
    )
    provider = db.get_provider("relay")
    assert provider is not None
    assert provider["name"] == "Relay"
    assert "api_key" not in provider
    assert "secret" not in str(provider).lower()


def test_wizard_autosave_round_trip(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_wizard("wizard", "draft", "long", {"steps": []}, {"title": {"value": "Book", "policy": "locked"}})
    wizard = db.get_wizard("wizard")
    assert wizard["status"] == "draft"
    assert wizard["answers"]["title"]["policy"] == "locked"


def test_interview_messages_round_trip_in_order(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_wizard("wizard", "draft", "long", {"steps": []}, {})

    db.save_interview_message("user-1", "wizard", "user", "我想写悬疑小说", [])
    db.save_interview_message("assistant-1", "wizard", "assistant", "主角最害怕什么？", [
        {"field_id": "genre", "value": "悬疑", "reason": "用户已明确"},
    ])
    db.update_interview_message_status("assistant-1", "applied")

    messages = db.list_interview_messages("wizard")
    assert [item["role"] for item in messages] == ["user", "assistant"]
    assert messages[1]["suggestions"][0]["field_id"] == "genre"
    assert messages[1]["suggestion_status"] == "applied"


def test_delete_wizard_cascades_interview_messages(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_wizard("draft-1", "draft", "short", {"steps": []}, {})
    db.save_interview_message(
        "message-1", "draft-1", "assistant", "先确定主角目标。", [],
    )

    assert db.delete_wizard("draft-1") is True
    assert db.get_wizard("draft-1") is None
    assert db.list_interview_messages("draft-1") == []
    assert db.delete_wizard("draft-1") is False


def test_delete_wizard_only_removes_unfinished_projectless_sessions(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    for status in ("draft", "gathering_input", "ready"):
        db.save_wizard(status, status, "short", {"steps": []}, {})
        assert db.delete_wizard(status) is True
    db.save_wizard("completed", "completed", "short", {"steps": []}, {})
    db.save_wizard(
        "linked", "draft", "short", {"steps": []}, {}, project_id="project-1",
    )

    assert db.delete_wizard("completed") is False
    assert db.delete_wizard("linked") is False
    assert db.get_wizard("completed") is not None
    assert db.get_wizard("linked") is not None


def test_locks_are_revisioned_and_proposals_are_persisted(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_lock("book", "story.ending", "Old ending", "wizard.ending")
    db.save_lock("book", "story.ending", "Approved ending", "change-request")
    assert [item["revision"] for item in db.list_locks("book")] == [2]
    assert db.list_locks("book")[0]["value"] == "Approved ending"

    db.create_skill_execution("execution", "book", "story-init", "hash")
    db.save_file_proposal("proposal", "execution", "story.md", "# Story", "pending")
    proposals = db.list_file_proposals("execution")
    assert proposals[0]["relative_path"] == "story.md"
    assert len(proposals[0]["content_hash"]) == 64


def test_completed_skill_execution_is_matched_by_project_skill_and_hash(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.create_skill_execution("old", "book", "story-init", "hash-a", "completed")

    assert db.has_completed_skill_execution("book", "story-init", "hash-a")
    assert not db.has_completed_skill_execution("book", "story-init", "hash-b")
    assert not db.has_completed_skill_execution("other", "story-init", "hash-a")


def test_recoverable_skill_execution_reports_preserved_proposals(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.create_skill_execution("execution", "book", "worldbuilding", "hash", "running")
    db.save_file_proposal(
        "primary", "execution", "worldbuilding/locations/home.md",
        "---\nname: 家\n---\n", "retained", "primary stopped",
    )
    db.save_file_proposal(
        "fallback", "execution", "worldbuilding/_index.md",
        "---\ntype: world-registry\n---\n", "failed", "fallback stopped",
    )
    db.update_skill_execution("execution", "recoverable", "fallback stopped")

    assert db.file_proposal_summary("execution") == {
        "execution_id": "execution",
        "total": 2,
        "recoverable_count": 2,
        "counts": {"failed": 1, "retained": 1},
    }
    recoverable = db.list_recoverable_skill_executions("book", "worldbuilding")
    assert [item["id"] for item in recoverable] == ["execution"]
    assert recoverable[0]["proposal_summary"]["recoverable_count"] == 2
