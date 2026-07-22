from novel_flywheel.db import Database


def test_database_creates_foundation_tables(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    assert {"providers", "models", "role_bindings", "schema_version", "run_events"} <= db.table_names()


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
