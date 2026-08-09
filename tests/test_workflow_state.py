import hashlib

import pytest

from novel_flywheel.db import Database
from novel_flywheel.workflow_state import CheckpointEnvelope


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def make_run(db: Database) -> None:
    db.save_project("book", "Book", "short", db.path.parent / "book")
    db.create_run("run", "book", "short-story")


def test_workflow_node_checkpoint_is_idempotent_and_hash_bound(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    make_run(db)
    values = {
        "run_id": "run", "node_key": "planning-segment-5",
        "authority_sha256": digest("authority"),
        "input_sha256": digest("input"),
        "output_sha256": digest("output"),
        "status": "validated", "payload": {"segment": 5},
    }

    first = db.save_workflow_node_checkpoint(**values)
    second = db.save_workflow_node_checkpoint(**values)
    loaded = db.load_workflow_node_checkpoint(
        run_id="run", node_key="planning-segment-5",
        authority_sha256=values["authority_sha256"],
        input_sha256=values["input_sha256"],
    )

    assert CheckpointEnvelope.model_validate(first).attempt == 1
    assert CheckpointEnvelope.model_validate(second).attempt == 2
    assert CheckpointEnvelope.model_validate(second).version == 2
    assert second["validation_stage"] == "promoted"
    assert loaded is not None and loaded["payload"] == {"segment": 5}


def test_stale_or_conflicting_checkpoint_cannot_resume(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    make_run(db)
    values = {
        "run_id": "run", "node_key": "draft-segment-2",
        "authority_sha256": digest("authority"),
        "input_sha256": digest("input"),
        "output_sha256": digest("accepted"),
        "status": "validated",
    }
    db.save_workflow_node_checkpoint(**values)

    assert db.load_workflow_node_checkpoint(
        run_id="run", node_key="draft-segment-2",
        authority_sha256=digest("new-authority"),
        input_sha256=digest("input"),
    ) is None
    with pytest.raises(ValueError, match="checkpoint conflict"):
        db.save_workflow_node_checkpoint(
            **{**values, "output_sha256": digest("conflict")},
        )


def test_validation_stages_promote_monotonically_and_resume_at_required_boundary(
    tmp_path,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    make_run(db)
    values = {
        "run_id": "run", "node_key": "planning-segment-1",
        "authority_sha256": digest("authority"),
        "input_sha256": digest("input"),
        "output_sha256": digest("candidate"),
        "status": "generated_complete",
    }
    db.save_workflow_node_checkpoint(
        **values, validation_stage="syntax",
    )
    db.save_workflow_node_checkpoint(
        **values, validation_stage="ownership",
    )

    assert db.load_workflow_node_checkpoint(
        run_id="run", node_key="planning-segment-1",
        authority_sha256=values["authority_sha256"],
        input_sha256=values["input_sha256"],
        statuses=("generated_complete",),
        min_validation_stage="ownership",
    ) is not None
    assert db.load_workflow_node_checkpoint(
        run_id="run", node_key="planning-segment-1",
        authority_sha256=values["authority_sha256"],
        input_sha256=values["input_sha256"],
        statuses=("generated_complete",),
        min_validation_stage="local_semantics",
    ) is None
    with pytest.raises(ValueError, match="stage regression"):
        db.save_workflow_node_checkpoint(
            **values, validation_stage="syntax",
        )


def test_v1_validated_checkpoint_migrates_idempotently_to_promoted(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    make_run(db)
    values = {
        "run_id": "run", "node_key": "legacy",
        "authority_sha256": digest("authority"),
        "input_sha256": digest("input"),
        "output_sha256": digest("accepted"),
        "status": "validated",
    }
    db.save_workflow_node_checkpoint(**values)
    with db.connect() as connection:
        connection.execute(
            "UPDATE workflow_node_checkpoints SET checkpoint_version=1, "
            "validation_stage='transport' WHERE node_key='legacy'"
        )

    db.migrate()
    db.migrate()
    loaded = db.load_workflow_node_checkpoint(
        run_id="run", node_key="legacy",
        authority_sha256=values["authority_sha256"],
        input_sha256=values["input_sha256"],
    )

    assert loaded is not None
    assert loaded["checkpoint_version"] == 2
    assert loaded["validation_stage"] == "promoted"


def test_generated_transport_output_is_not_resumable_as_validated_authority(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    make_run(db)
    db.save_workflow_node_checkpoint(
        run_id="run", node_key="review",
        authority_sha256=digest("authority"), input_sha256=digest("input"),
        output_sha256=digest("model-output"), status="generated_complete",
    )

    assert db.load_workflow_node_checkpoint(
        run_id="run", node_key="review",
        authority_sha256=digest("authority"), input_sha256=digest("input"),
    ) is None
