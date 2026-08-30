from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path

import pytest

from novel_flywheel.db import Database
from novel_flywheel.projects import ProjectCreate, ProjectStore
from novel_flywheel.skills import SkillScanner
from novel_flywheel.story_state import StoryStateStore
from tools.canary import first_trustworthy_full_short_runner as runner


def _bound_project(tmp_path: Path) -> tuple[Path, Path, str, Database]:
    repo = tmp_path / "repo"
    data = tmp_path / "data"
    repo.mkdir()
    db = Database(data / "app.db")
    db.migrate()
    db.save_provider(
        provider_id="provider", name="Provider", protocol="anthropic",
        base_url="https://unit.test/v1", auth_type="x-api-key",
        timeout_seconds=30, extra_headers={},
    )
    db.save_model(
        model_id="model", provider_id="provider", display_name="Model",
        model_name="model", context_window=None, max_output_tokens=None,
    )
    for role in runner.FULL_SHORT_REQUIRED_EXECUTION_ROLES:
        db.save_role_binding(role, "provider", "model", None, None)
    projects = ProjectStore(db, data / "projects")
    project = projects.create(ProjectCreate(
        title="Bound", mode="short", genre="mystery",
        premise="A bound authority is verified.", target_words=13_000,
    ))
    StoryStateStore(db).ensure(project.id, project.path)
    db.set_feature_flag(
        "short_canonical_v2", True,
        scope_type="project", scope_id=project.id,
    )
    for skill in SkillScanner([
        Path.home() / ".codex" / "skills",
    ]).scan():
        if skill.executable:
            db.approve_skill(skill.name, skill.content_hash)
    return repo, data, project.id, db


def test_live_bindings_seal_v2_runtime_skill_style_and_store_source_truth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, data, project_id, _db = _bound_project(tmp_path)
    monkeypatch.setenv("NOVEL_SHORT_CANONICAL_V2", "1")
    store_root = tmp_path / "control-store"
    monkeypatch.setattr(runner, "_git", lambda _repo, *args: (
        "a" * 40 if args == ("rev-parse", "HEAD")
        else "hardening" if args == ("branch", "--show-current")
        else ""
    ))

    actual, public = runner.collect_live_bindings(
        repo=repo, data_dir=data, project_id=project_id,
        run_id="hardening", store_root=store_root,
    )

    runtime = public["runtime_authority"]
    production = public["production_path_identity"]
    assert runtime["runtime_fingerprint_policy_version"] == "runtime-fingerprint-v2"
    assert runtime["story_state_source_truth"] == "sqlite.story_states.current_revision"
    assert runtime["maintenance_source_state_sha256"]
    assert public["style_reference_authority"]["prose_baseline_state"] == "missing"
    assert "quality_reference_group_version" in public["style_reference_authority"]
    assert production["current_baseline_skill_stage_bytes"]
    assert production["prompt_compactor_configuration"][
        "skill_prompt_compactor_max_characters"
    ] == 9000
    assert production["cutover_source_truth"]["derivation"] == (
        "python_ast_and_constructor_signature"
    )
    assert public["store_root"] == str(store_root.resolve())
    assert actual["store_root_sha256"] == hashlib.sha256(
        str(store_root.resolve()).encode("utf-8")
    ).hexdigest()


def test_live_bindings_reject_missing_ready_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, data, project_id, db = _bound_project(tmp_path)
    monkeypatch.setenv("NOVEL_SHORT_CANONICAL_V2", "1")
    db.set_feature_flag(
        "short_canonical_v2", False,
        scope_type="project", scope_id=project_id,
    )
    monkeypatch.setattr(runner, "_git", lambda *_args: "")
    with pytest.raises(ValueError, match="READY authority"):
        runner.collect_live_bindings(
            repo=repo, data_dir=data, project_id=project_id,
            run_id="hardening", store_root=tmp_path / "control-store",
        )


def test_completion_elapsed_is_rechecked_after_last_dispatch() -> None:
    expired = (
        datetime.now(timezone.utc) - timedelta(seconds=10)
    ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    with pytest.raises(RuntimeError, match="EXPIRED_AT_COMPLETION"):
        runner._completion_elapsed_recheck(
            {"maximum_elapsed_seconds": 1}, {"created_at": expired},
        )


def test_dry_run_has_no_test_owned_oracle_or_fixed_call_count() -> None:
    source = (
        Path(runner.__file__).with_name(
            "first_trustworthy_full_short_dry_run.py"
        ).read_text(encoding="utf-8")
    )
    assert "tests.test_" not in source
    assert "expected_stage_calls=1" not in source
    assert "execute_full_short_control_plane(" in source
    assert "run_full_short_workflow_path(" in source
