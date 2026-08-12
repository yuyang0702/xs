from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from novel_flywheel.db import Database
from novel_flywheel.storage import atomic_write


class LearningArtifactInvalidationV1(BaseModel):
    """One exact, idempotent DB transition owned by a project mutation.

    The row identity and immutable source hash are frozen before project files
    are changed.  Recovery may therefore repeat the transition, but it may not
    invalidate a newer or otherwise unrelated learning artifact.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1] = 1
    artifact_id: str = Field(min_length=1)
    artifact_type: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    artifact_version: int = Field(ge=1)
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    from_status: Literal["active"] = "active"
    to_status: Literal["stale"] = "stale"


class LearningArtifactInvalidationPlanV1(BaseModel):
    """Runtime-owned invalidation authority plus readable sidecar targets."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1] = 1
    project_id: str = Field(min_length=1)
    effects: tuple[LearningArtifactInvalidationV1, ...] = ()
    sidecars: dict[str, dict[str, Any]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_topology(self) -> "LearningArtifactInvalidationPlanV1":
        identities = [item.artifact_id for item in self.effects]
        if len(identities) != len(set(identities)):
            raise ValueError("learning artifact invalidations are duplicated")
        effect_types = {item.artifact_type for item in self.effects}
        if set(self.sidecars) != effect_types:
            raise ValueError("learning artifact sidecar coverage is incomplete")
        for artifact_type, payload in self.sidecars.items():
            if payload.get("status") != "stale":
                raise ValueError("learning artifact sidecar is not stale")
            matching = [
                item for item in self.effects
                if item.artifact_type == artifact_type
            ]
            latest = max(matching, key=lambda item: item.artifact_version)
            if (
                payload.get("id") != latest.artifact_id
                or payload.get("version") != latest.artifact_version
                or payload.get("source_hash") != latest.source_hash
            ):
                raise ValueError("learning artifact sidecar authority is stale")
        return self


def artifact_sidecar_payload(row: Any, *, status: str | None = None) -> dict:
    value = dict(row)
    data = value.get("data")
    if not isinstance(data, dict):
        data = json.loads(value["data_json"])
    return {
        "id": value["id"],
        "version": int(value["version"]),
        "status": status or value["status"],
        "source_hash": value["source_hash"],
        "data": data,
    }


def plan_learning_artifact_invalidations(
    db: Database,
    project_id: str,
    *,
    artifact_types: Sequence[str] | None = None,
    latest_only: bool = False,
) -> LearningArtifactInvalidationPlanV1:
    """Freeze exactly which active artifact rows a business change invalidates.

    ``latest_only`` preserves the pre-refactor outline behavior.  Material
    changes intentionally invalidate every active version, matching the old
    business rule.  The distinction is explicit data, not a hidden branch in
    the transaction engine.
    """

    parameters: list[Any] = [project_id]
    filters = ["project_id=?", "status='active'"]
    if artifact_types is not None:
        normalized = tuple(dict.fromkeys(str(item) for item in artifact_types))
        if not normalized:
            return LearningArtifactInvalidationPlanV1(project_id=project_id)
        filters.append(
            "artifact_type IN (" + ",".join("?" for _ in normalized) + ")"
        )
        parameters.extend(normalized)
    query = (
        "SELECT * FROM project_learning_artifacts WHERE "
        + " AND ".join(filters)
        + " ORDER BY artifact_type,version,id"
    )
    with db.connect() as connection:
        rows = list(connection.execute(query, parameters).fetchall())
    if latest_only:
        by_type: dict[str, Any] = {}
        for row in rows:
            by_type[str(row["artifact_type"])] = row
        rows = list(by_type.values())
    effects = tuple(
        LearningArtifactInvalidationV1(
            artifact_id=str(row["id"]),
            artifact_type=str(row["artifact_type"]),
            artifact_version=int(row["version"]),
            source_hash=str(row["source_hash"]),
        )
        for row in rows
    )
    latest_rows: dict[str, Any] = {}
    for row in rows:
        latest_rows[str(row["artifact_type"])] = row
    return LearningArtifactInvalidationPlanV1(
        project_id=project_id,
        effects=effects,
        sidecars={
            artifact_type: artifact_sidecar_payload(row, status="stale")
            for artifact_type, row in latest_rows.items()
        },
    )


def write_learning_artifact_sidecar_targets(
    project_path: Path,
    plan: LearningArtifactInvalidationPlanV1,
) -> list[Path]:
    paths: list[Path] = []
    for artifact_type, payload in sorted(plan.sidecars.items()):
        path = project_path / "learning" / f"{artifact_type}.json"
        atomic_write(
            path,
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            preserve_newlines=True,
        )
        paths.append(path)
    return paths


def apply_learning_artifact_invalidations(
    db: Database,
    project_id: str,
    effects: Sequence[LearningArtifactInvalidationV1],
) -> None:
    """Apply a frozen invalidation ledger atomically and idempotently."""

    with db.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        rows = []
        for effect in effects:
            row = connection.execute(
                "SELECT project_id,artifact_type,version,status,source_hash "
                "FROM project_learning_artifacts WHERE id=?",
                (effect.artifact_id,),
            ).fetchone()
            if row is None:
                raise ValueError("learning artifact invalidation target is missing")
            if (
                str(row["project_id"]) != project_id
                or str(row["artifact_type"]) != effect.artifact_type
                or int(row["version"]) != effect.artifact_version
                or str(row["source_hash"]) != effect.source_hash
            ):
                raise ValueError("learning artifact invalidation authority is stale")
            if str(row["status"]) not in {
                effect.from_status, effect.to_status,
            }:
                raise ValueError("learning artifact status changed concurrently")
            rows.append((effect.artifact_id, str(row["status"])))
        for artifact_id, status in rows:
            if status == "active":
                connection.execute(
                    "UPDATE project_learning_artifacts SET status='stale' "
                    "WHERE id=? AND status='active'",
                    (artifact_id,),
                )
