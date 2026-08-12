import hashlib
import json

import pytest

from novel_flywheel.db import Database
from novel_flywheel.learning_artifacts import (
    apply_learning_artifact_invalidations,
    plan_learning_artifact_invalidations,
    write_learning_artifact_sidecar_targets,
)
from novel_flywheel.projects import ProjectCreate, ProjectStore


def _project_with_artifacts(tmp_path):
    db = Database(tmp_path / "app.db")
    db.migrate()
    projects = ProjectStore(db, tmp_path / "projects")
    project = projects.create(ProjectCreate(
        title="事务验证", mode="short", genre="悬疑",
        premise="一份资料改变了既有权威。", target_words=13_000,
    ))
    rows = []
    with db.connect() as connection:
        for artifact_type, version in (
            ("scene_briefs", 1), ("scene_briefs", 2),
            ("short_causal_chain", 1), ("voice_profiles", 1),
        ):
            data = {"artifact_type": artifact_type, "version": version}
            serialized = json.dumps(data, ensure_ascii=False, sort_keys=True)
            digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
            artifact_id = f"{artifact_type}-{version}"
            connection.execute(
                "INSERT INTO project_learning_artifacts VALUES "
                "(?,?,?,?,?,?,?,datetime('now'))",
                (artifact_id, project.id, artifact_type, version, "active",
                 serialized, digest),
            )
            rows.append((artifact_id, artifact_type, version, digest))
    return db, project, rows


def test_material_change_plan_preserves_all_active_version_behavior(tmp_path) -> None:
    db, project, _rows = _project_with_artifacts(tmp_path)

    plan = plan_learning_artifact_invalidations(db, project.id)
    paths = write_learning_artifact_sidecar_targets(project.path, plan)
    apply_learning_artifact_invalidations(db, project.id, plan.effects)
    apply_learning_artifact_invalidations(db, project.id, plan.effects)

    assert len(plan.effects) == 4
    assert {path.name for path in paths} == {
        "scene_briefs.json", "short_causal_chain.json", "voice_profiles.json",
    }
    with db.connect() as connection:
        statuses = connection.execute(
            "SELECT status FROM project_learning_artifacts WHERE project_id=?",
            (project.id,),
        ).fetchall()
    assert {row["status"] for row in statuses} == {"stale"}
    scene = json.loads(
        (project.path / "learning" / "scene_briefs.json").read_text(
            encoding="utf-8",
        )
    )
    assert scene["version"] == 2
    assert scene["status"] == "stale"


def test_outline_plan_preserves_latest_selected_type_behavior(tmp_path) -> None:
    db, project, _rows = _project_with_artifacts(tmp_path)

    plan = plan_learning_artifact_invalidations(
        db, project.id,
        artifact_types=("scene_briefs", "short_causal_chain"),
        latest_only=True,
    )

    assert [(item.artifact_type, item.artifact_version) for item in plan.effects] == [
        ("scene_briefs", 2), ("short_causal_chain", 1),
    ]
    assert set(plan.sidecars) == {"scene_briefs", "short_causal_chain"}


def test_invalidation_refuses_stale_or_cross_project_authority(tmp_path) -> None:
    db, project, _rows = _project_with_artifacts(tmp_path)
    plan = plan_learning_artifact_invalidations(
        db, project.id, artifact_types=("voice_profiles",),
    )
    effect = plan.effects[0]
    with db.connect() as connection:
        connection.execute(
            "UPDATE project_learning_artifacts SET source_hash=? WHERE id=?",
            ("0" * 64, effect.artifact_id),
        )

    with pytest.raises(ValueError, match="authority is stale"):
        apply_learning_artifact_invalidations(db, project.id, plan.effects)


def test_invalidation_validates_entire_ledger_before_any_update(tmp_path) -> None:
    db, project, _rows = _project_with_artifacts(tmp_path)
    plan = plan_learning_artifact_invalidations(
        db, project.id,
        artifact_types=("scene_briefs", "short_causal_chain"),
        latest_only=True,
    )
    first, second = plan.effects
    with db.connect() as connection:
        connection.execute(
            "UPDATE project_learning_artifacts SET source_hash=? WHERE id=?",
            ("f" * 64, second.artifact_id),
        )

    with pytest.raises(ValueError, match="authority is stale"):
        apply_learning_artifact_invalidations(db, project.id, plan.effects)

    with db.connect() as connection:
        status = connection.execute(
            "SELECT status FROM project_learning_artifacts WHERE id=?",
            (first.artifact_id,),
        ).fetchone()["status"]
    assert status == "active"
