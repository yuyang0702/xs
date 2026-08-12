from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Annotated, Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from novel_flywheel.storage import (
    ProjectSnapshot,
    atomic_write,
    atomic_write_bytes,
)
from novel_flywheel.learning_artifacts import (
    LearningArtifactInvalidationV1,
    apply_learning_artifact_invalidations,
)
from novel_flywheel.story_state import StoryStateStore


PROJECT_MUTATION_JOURNAL = "project-mutation-journal.json"


def canonical_json_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _relative_project_path(project_root: Path, path: Path) -> str:
    root = project_root.resolve()
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("Project mutation path is outside the project")
    relative = resolved.relative_to(root).as_posix()
    if not relative or relative.startswith("../"):
        raise ValueError("Project mutation path is invalid")
    return relative


class ProjectMutationArtifactV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ProjectMutationPostCommitGateV1(BaseModel):
    """Opaque, hash-bound business gate owned outside the Saga kernel."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    name: str = Field(min_length=1)
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload: dict[str, Any]
    status: Literal["pending", "passed", "blocked"] = "pending"
    receipt_path: str | None = None
    receipt_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$",
    )

    @model_validator(mode="after")
    def validate_payload(self) -> "ProjectMutationPostCommitGateV1":
        if canonical_json_sha256(self.payload) != self.payload_sha256:
            raise ValueError("Project mutation post-commit gate hash is stale")
        has_receipt = bool(self.receipt_path and self.receipt_sha256)
        if self.status == "pending" and (
            self.receipt_path is not None or self.receipt_sha256 is not None
        ):
            raise ValueError("Pending project mutation gate cannot claim a receipt")
        if self.status != "pending" and not has_receipt:
            raise ValueError("Resolved project mutation gate lacks its receipt")
        if self.receipt_path:
            path = Path(self.receipt_path)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("Project mutation gate receipt path is invalid")
        return self


class ProjectMutationStoryStateV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str = Field(min_length=1)
    expected_revision: int = Field(ge=1)
    target_revision: int = Field(ge=2)
    state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    data: dict[str, Any]

    @model_validator(mode="after")
    def validate_authority(self) -> "ProjectMutationStoryStateV1":
        if self.target_revision != self.expected_revision + 1:
            raise ValueError("Project mutation StoryState revision is invalid")
        if canonical_json_sha256(self.data) != self.state_sha256:
            raise ValueError("Project mutation StoryState hash is stale")
        return self


class ProjectMutationCanonFactV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    kind: Literal["canon_fact"] = "canon_fact"
    fact_key: str = Field(min_length=1)
    value: str
    source: str = Field(min_length=1)
    confirmed: bool = True
    preserve_existing: bool = True


class ProjectMutationChapterIndexV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    kind: Literal["chapter_index"] = "chapter_index"
    chapter_id: str = Field(min_length=1)
    chapter_number: int = Field(ge=1)
    content: str = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    summary: str

    @model_validator(mode="after")
    def validate_content(self) -> "ProjectMutationChapterIndexV1":
        if hashlib.sha256(self.content.encode("utf-8")).hexdigest() != (
            self.content_sha256
        ):
            raise ValueError("Project mutation chapter-index hash is stale")
        return self


class ProjectMutationChapterStateV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    kind: Literal["chapter_state"] = "chapter_state"
    chapter_id: str = Field(min_length=1)
    state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    state: dict[str, Any]

    @model_validator(mode="after")
    def validate_state(self) -> "ProjectMutationChapterStateV1":
        if canonical_json_sha256(self.state) != self.state_sha256:
            raise ValueError("Project mutation chapter-state hash is stale")
        return self


ProjectMutationMemoryEffectV1 = Annotated[
    ProjectMutationCanonFactV1
    | ProjectMutationChapterIndexV1
    | ProjectMutationChapterStateV1,
    Field(discriminator="kind"),
]


class ProjectMutationJournalV1(BaseModel):
    """Versioned, content-addressed Saga for project files plus StoryState.

    ``prepared`` owns only the rollback snapshot. ``artifacts_committed`` also
    owns immutable target copies and may be completed after a restart.
    ``committed`` means both the file set and optional StoryState transition
    are authoritative; only the terminal run row may still need finalizing.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1] = 1
    status: Literal[
        "prepared", "artifacts_committed", "committed", "rolled_back"
    ]
    operation: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    snapshot_path: str = Field(min_length=1)
    source_authority_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_story_state_revision: int = Field(ge=1)
    managed_paths: tuple[str, ...] = Field(min_length=1)
    artifacts: tuple[ProjectMutationArtifactV1, ...] = ()
    story_state: ProjectMutationStoryStateV1 | None = None
    post_commit_gate: ProjectMutationPostCommitGateV1 | None = None
    memory_effects: tuple[ProjectMutationMemoryEffectV1, ...] = ()
    learning_artifact_invalidations: tuple[
        LearningArtifactInvalidationV1, ...
    ] = ()

    @model_validator(mode="after")
    def validate_topology(self) -> "ProjectMutationJournalV1":
        if len(set(self.managed_paths)) != len(self.managed_paths):
            raise ValueError("Project mutation managed paths are duplicated")
        for path in self.managed_paths:
            candidate = Path(path)
            if candidate.is_absolute() or ".." in candidate.parts:
                raise ValueError("Project mutation managed path is invalid")
        artifact_paths = tuple(item.path for item in self.artifacts)
        if len(set(artifact_paths)) != len(artifact_paths):
            raise ValueError("Project mutation artifact paths are duplicated")
        if self.status in {"artifacts_committed", "committed"}:
            if set(artifact_paths) != set(self.managed_paths):
                raise ValueError("Project mutation artifact coverage is incomplete")
        elif self.artifacts:
            raise ValueError("Uncommitted project mutation cannot claim target artifacts")
        if self.story_state is not None and (
            self.story_state.expected_revision
            != self.expected_story_state_revision
        ):
            raise ValueError("Project mutation StoryState base revision is stale")
        invalidation_ids = [
            item.artifact_id for item in self.learning_artifact_invalidations
        ]
        if len(invalidation_ids) != len(set(invalidation_ids)):
            raise ValueError("Project mutation learning invalidations are duplicated")
        for item in self.learning_artifact_invalidations:
            sidecar = f"learning/{item.artifact_type}.json"
            if sidecar not in self.managed_paths:
                raise ValueError(
                    "Project mutation learning invalidation lacks its sidecar"
                )
        memory_keys = []
        for item in self.memory_effects:
            if isinstance(item, ProjectMutationCanonFactV1):
                identity = (item.kind, item.fact_key, item.confirmed)
            else:
                identity = (item.kind, item.chapter_id)
            memory_keys.append(identity)
        if len(memory_keys) != len(set(memory_keys)):
            raise ValueError("Project mutation memory effects are duplicated")
        return self


class _ProjectStore(Protocol):
    db: Any

    def get(self, project_id: str) -> Any: ...


def project_mutation_journal_path(project_root: Path, run_id: str) -> Path:
    return (
        project_root / "runs" / run_id / "outputs"
        / PROJECT_MUTATION_JOURNAL
    )


def write_project_mutation_journal(
    path: Path, journal: ProjectMutationJournalV1,
) -> None:
    atomic_write(
        path,
        json.dumps(
            journal.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n",
        preserve_newlines=True,
    )


def load_project_mutation_journal(path: Path) -> ProjectMutationJournalV1:
    return ProjectMutationJournalV1.model_validate_json(
        path.read_text(encoding="utf-8"),
    )


def stage_project_mutation_targets(
    project_root: Path,
    snapshot: ProjectSnapshot,
    paths: list[Path],
) -> tuple[ProjectMutationArtifactV1, ...]:
    """Persist an immutable forward-recovery copy of the exact target bytes."""

    artifacts = []
    for path in paths:
        relative = _relative_project_path(project_root, path)
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        atomic_write_bytes(snapshot.snapshot_root / "targets" / relative, content)
        artifacts.append(ProjectMutationArtifactV1(path=relative, sha256=digest))
    return tuple(sorted(artifacts, key=lambda item: item.path))


def _snapshot_original_sha256(
    snapshot: ProjectSnapshot, relative_path: str,
) -> str | None:
    for entry in snapshot.entries:
        if entry["path"] == relative_path:
            return str(entry["sha256"]) if entry.get("sha256") else None
    raise ValueError("Project mutation path is absent from its rollback snapshot")


def restore_project_mutation_targets(
    project_root: Path,
    snapshot: ProjectSnapshot,
    artifacts: tuple[ProjectMutationArtifactV1, ...],
) -> None:
    """Idempotently roll forward only from the old or already-target bytes.

    A third hash means an out-of-band writer changed the project while this
    Saga was pending. Refuse to overwrite that unknown authority.
    """

    pending_writes: list[tuple[Path, bytes]] = []
    for artifact in artifacts:
        destination = project_root / artifact.path
        target = snapshot.snapshot_root / "targets" / artifact.path
        target_bytes = target.read_bytes()
        if hashlib.sha256(target_bytes).hexdigest() != artifact.sha256:
            raise ValueError("Project mutation staged target is corrupt")
        current_sha256 = (
            hashlib.sha256(destination.read_bytes()).hexdigest()
            if destination.is_file() else None
        )
        original_sha256 = _snapshot_original_sha256(snapshot, artifact.path)
        if current_sha256 == artifact.sha256:
            continue
        if current_sha256 != original_sha256:
            raise ValueError("Project mutation target has an unknown concurrent edit")
        pending_writes.append((destination, target_bytes))
    # Validate the entire managed set before changing a single destination.
    # A late conflict can therefore never leave a partially rolled-forward
    # project merely because its path sorted after an uncontested artifact.
    for destination, target_bytes in pending_writes:
        atomic_write_bytes(destination, target_bytes)


def project_mutation_artifacts_match(
    project_root: Path,
    artifacts: tuple[ProjectMutationArtifactV1, ...],
) -> bool:
    for artifact in artifacts:
        path = project_root / artifact.path
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            return False
        if digest != artifact.sha256:
            return False
    return True


def apply_project_memory_effects(
    store: _ProjectStore, project_id: str,
    effects: tuple[ProjectMutationMemoryEffectV1, ...],
) -> None:
    """Apply an idempotent, journal-owned StoryMemory projection in one DB tx."""

    if not effects:
        return
    with store.db.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        for effect in effects:
            if isinstance(effect, ProjectMutationCanonFactV1):
                connection.execute(
                    "INSERT INTO canon_facts "
                    "(project_id, fact_key, value, source, confirmed, created_at) "
                    "VALUES (?, ?, ?, ?, ?, datetime('now')) "
                    + (
                        "ON CONFLICT(project_id, fact_key, confirmed) DO NOTHING"
                        if effect.preserve_existing else
                        "ON CONFLICT(project_id, fact_key, confirmed) DO UPDATE SET "
                        "value=excluded.value, source=excluded.source"
                    ),
                    (
                        project_id, effect.fact_key, effect.value,
                        effect.source, int(effect.confirmed),
                    ),
                )
            elif isinstance(effect, ProjectMutationChapterIndexV1):
                connection.execute(
                    "DELETE FROM chapter_search "
                    "WHERE project_id=? AND chapter_id=?",
                    (project_id, effect.chapter_id),
                )
                connection.execute(
                    "INSERT INTO chapter_search VALUES (?, ?, ?, ?, ?)",
                    (
                        project_id, effect.chapter_id, effect.chapter_number,
                        effect.content, effect.summary,
                    ),
                )
            else:
                connection.execute(
                    "INSERT INTO chapter_states "
                    "(project_id, chapter_id, state_json, created_at) "
                    "VALUES (?, ?, ?, datetime('now')) "
                    "ON CONFLICT(project_id, chapter_id) DO UPDATE SET "
                    "state_json=excluded.state_json, "
                    "created_at=excluded.created_at",
                    (
                        project_id, effect.chapter_id,
                        json.dumps(effect.state, ensure_ascii=False),
                    ),
                )


def project_memory_effects_match(
    store: _ProjectStore, project_id: str,
    effects: tuple[ProjectMutationMemoryEffectV1, ...],
) -> bool:
    if not effects:
        return True
    with store.db.connect() as connection:
        for effect in effects:
            if isinstance(effect, ProjectMutationCanonFactV1):
                row = connection.execute(
                    "SELECT value, source FROM canon_facts "
                    "WHERE project_id=? AND fact_key=? AND confirmed=?",
                    (project_id, effect.fact_key, int(effect.confirmed)),
                ).fetchone()
                if row is None:
                    return False
                if (
                    not effect.preserve_existing
                    and (str(row["value"]), str(row["source"]))
                    != (effect.value, effect.source)
                ):
                    return False
            elif isinstance(effect, ProjectMutationChapterIndexV1):
                rows = connection.execute(
                    "SELECT chapter_number, content, summary FROM chapter_search "
                    "WHERE project_id=? AND chapter_id=?",
                    (project_id, effect.chapter_id),
                ).fetchall()
                if len(rows) != 1:
                    return False
                row = rows[0]
                if (
                    int(row["chapter_number"]), str(row["content"]),
                    str(row["summary"]),
                ) != (
                    effect.chapter_number, effect.content, effect.summary,
                ):
                    return False
            else:
                row = connection.execute(
                    "SELECT state_json FROM chapter_states "
                    "WHERE project_id=? AND chapter_id=?",
                    (project_id, effect.chapter_id),
                ).fetchone()
                if row is None:
                    return False
                try:
                    state = json.loads(row["state_json"])
                except (TypeError, json.JSONDecodeError):
                    return False
                if canonical_json_sha256(state) != effect.state_sha256:
                    return False
    return True


def _reject_pending_candidates_for_run(
    state_store: StoryStateStore, project_id: str, run_id: str, reason: str,
) -> None:
    for candidate in state_store.list_candidates(
        project_id, status="pending",
    ):
        if candidate.run_id == run_id:
            state_store.reject(candidate.id, reason)


def rollback_project_mutation(
    store: _ProjectStore,
    journal_path: Path,
    journal: ProjectMutationJournalV1,
    snapshot: ProjectSnapshot,
    *,
    error: str,
) -> None:
    snapshot.restore()
    state_store = StoryStateStore(store.db)
    _reject_pending_candidates_for_run(
        state_store, journal.project_id, journal.run_id,
        "project mutation rolled back",
    )
    rolled_back = journal.model_copy(update={"status": "rolled_back"})
    write_project_mutation_journal(journal_path, rolled_back)
    store.db.update_run(journal.run_id, "failed", error=error)
    snapshot.discard()


def abort_project_mutation_request(
    store: _ProjectStore,
    run_id: str,
    snapshot: ProjectSnapshot | None,
    journal_path: Path | None,
    journal: ProjectMutationJournalV1 | None,
    *,
    error: str,
) -> bool:
    """Roll back only before the durable forward-recovery commit point.

    Returns ``False`` when an artifact bundle is already durable. In that
    case the caller must retain the run and snapshot so normal/startup
    recovery can finish the exact mutation instead of reverting accepted
    business authority.
    """

    if snapshot is None or journal_path is None or journal is None:
        store.db.update_run(run_id, "failed", error=error)
        return True
    try:
        latest = load_project_mutation_journal(journal_path)
    except Exception:
        latest = journal
    if latest.status != "prepared":
        return False
    rollback_project_mutation(
        store, journal_path, latest, snapshot, error=error,
    )
    return True


def _advance_project_mutation(
    store: _ProjectStore,
    run_id: str,
    *,
    finalize_run: bool,
    allow_post_commit_gate: bool,
) -> ProjectMutationJournalV1:
    """Advance one Saga without interpreting its domain-owned business gate."""

    run = store.db.get_run(run_id)
    if run is None:
        raise LookupError("Project mutation run is unavailable")
    project = store.get(str(run["project_id"]))
    journal_path = project_mutation_journal_path(project.path, run_id)
    journal = load_project_mutation_journal(journal_path)
    if (
        journal.run_id != run_id
        or journal.project_id != project.id
        or journal.operation != str(run["workflow"])
    ):
        raise ValueError("Project mutation journal identity is stale")
    if (
        finalize_run
        and journal.post_commit_gate is not None
        and not allow_post_commit_gate
    ):
        raise RuntimeError(
            "Project mutation requires its business post-commit gate"
        )
    if finalize_run and journal.post_commit_gate is not None:
        gate = journal.post_commit_gate
        if gate.status != "passed":
            raise RuntimeError("Project mutation post-commit gate has not passed")
        receipt_path = project.path / str(gate.receipt_path)
        try:
            receipt_sha256 = hashlib.sha256(
                receipt_path.read_bytes()
            ).hexdigest()
        except OSError as exc:
            raise RuntimeError(
                "Project mutation post-commit gate receipt is unavailable"
            ) from exc
        if receipt_sha256 != gate.receipt_sha256:
            raise RuntimeError(
                "Project mutation post-commit gate receipt is stale"
            )
    snapshot_path = project.path / journal.snapshot_path
    if journal.status == "rolled_back":
        store.db.update_run(run_id, "failed", error="Project mutation was rolled back.")
        if snapshot_path.is_dir():
            ProjectSnapshot.load(project.path, snapshot_path).discard()
        return journal

    state_store = StoryStateStore(store.db)
    current = state_store.get(project.id)
    if current is None:
        raise LookupError("Project mutation StoryState is unavailable")
    target = journal.story_state
    if journal.status == "committed":
        if not project_mutation_artifacts_match(project.path, journal.artifacts):
            raise RuntimeError("Committed project mutation artifacts are stale")
        if target is None:
            if current.revision != journal.expected_story_state_revision:
                raise ValueError("Committed project mutation StoryState is stale")
        else:
            candidate = state_store.get_candidate(target.candidate_id)
            if not (
                current.revision == target.target_revision
                and canonical_json_sha256(current.data) == target.state_sha256
                and candidate is not None
                and candidate.status == "accepted"
            ):
                raise ValueError("Committed project mutation StoryState is stale")
        if not project_memory_effects_match(
            store, project.id, journal.memory_effects,
        ):
            raise ValueError("Committed project mutation memory projection is stale")
        apply_learning_artifact_invalidations(
            store.db, project.id, journal.learning_artifact_invalidations,
        )
        if finalize_run:
            store.db.update_run(run_id, "completed", "archive", error=None)
            terminal = store.db.get_run(run_id)
            if terminal is None or terminal.get("status") != "completed":
                raise RuntimeError("Project mutation terminal state was not durable")
            if snapshot_path.is_dir():
                ProjectSnapshot.load(project.path, snapshot_path).discard()
        return journal

    snapshot = ProjectSnapshot.load(project.path, snapshot_path)
    if journal.status == "prepared":
        rollback_project_mutation(
            store, journal_path, journal, snapshot,
            error="Interrupted project mutation was rolled back.",
        )
        return journal.model_copy(update={"status": "rolled_back"})

    restore_project_mutation_targets(project.path, snapshot, journal.artifacts)
    if not project_mutation_artifacts_match(project.path, journal.artifacts):
        raise RuntimeError("Project mutation target verification failed")

    if target is None:
        if current.revision != journal.expected_story_state_revision:
            raise ValueError("Project mutation StoryState changed concurrently")
    else:
        candidate = state_store.get_candidate(target.candidate_id)
        current_sha256 = canonical_json_sha256(current.data)
        if (
            current.revision == target.target_revision
            and current_sha256 == target.state_sha256
            and candidate is not None
            and candidate.status == "accepted"
        ):
            pass
        elif (
            current.revision == target.expected_revision
            and candidate is not None
            and candidate.status == "pending"
        ):
            current = state_store.commit(
                target.candidate_id, target.expected_revision, target.data,
            )
            if (
                current.revision != target.target_revision
                or canonical_json_sha256(current.data) != target.state_sha256
            ):
                raise RuntimeError("Project mutation StoryState commit is stale")
        else:
            raise ValueError("Project mutation StoryState authority is stale")

    apply_project_memory_effects(
        store, project.id, journal.memory_effects,
    )
    if not project_memory_effects_match(
        store, project.id, journal.memory_effects,
    ):
        raise RuntimeError("Project mutation memory projection failed")

    apply_learning_artifact_invalidations(
        store.db, project.id, journal.learning_artifact_invalidations,
    )

    if journal.status != "committed":
        journal = journal.model_copy(update={"status": "committed"})
        write_project_mutation_journal(journal_path, journal)
    if finalize_run:
        store.db.update_run(run_id, "completed", "archive", error=None)
        terminal = store.db.get_run(run_id)
        if terminal is None or terminal.get("status") != "completed":
            raise RuntimeError("Project mutation terminal state was not durable")
        snapshot.discard()
    return journal


def commit_project_mutation_authority(
    store: _ProjectStore,
    run_id: str,
) -> ProjectMutationJournalV1:
    """Commit files/state/memory while leaving a later business gate pending."""

    return _advance_project_mutation(
        store, run_id, finalize_run=False, allow_post_commit_gate=False,
    )


def finalize_project_mutation(
    store: _ProjectStore,
    run_id: str,
) -> ProjectMutationJournalV1:
    """Finalize a two-phase Saga after its domain owner proves the gate."""

    return _advance_project_mutation(
        store, run_id, finalize_run=True, allow_post_commit_gate=True,
    )


def record_project_mutation_gate_result(
    store: _ProjectStore,
    run_id: str,
    *,
    status: Literal["passed", "blocked"],
    receipt_path: Path,
) -> ProjectMutationJournalV1:
    """Bind a domain-validated gate receipt without interpreting its content."""

    run = store.db.get_run(run_id)
    if run is None:
        raise LookupError("Project mutation run is unavailable")
    project = store.get(str(run["project_id"]))
    journal_path = project_mutation_journal_path(project.path, run_id)
    journal = load_project_mutation_journal(journal_path)
    if journal.status != "committed" or journal.post_commit_gate is None:
        raise ValueError("Project mutation post-commit gate is unavailable")
    relative = _relative_project_path(project.path, receipt_path)
    digest = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    current_gate = journal.post_commit_gate
    if current_gate.status != "pending":
        if (
            current_gate.status,
            current_gate.receipt_path,
            current_gate.receipt_sha256,
        ) != (status, relative, digest):
            raise ValueError("Project mutation gate result conflicts with authority")
        return journal
    gate = current_gate.model_copy(update={
        "status": status,
        "receipt_path": relative,
        "receipt_sha256": digest,
    })
    journal = ProjectMutationJournalV1.model_validate(
        journal.model_copy(update={
            "post_commit_gate": gate,
        }).model_dump(mode="python"),
    )
    write_project_mutation_journal(journal_path, journal)
    return journal


def complete_project_mutation(
    store: _ProjectStore,
    run_id: str,
) -> ProjectMutationJournalV1:
    """Complete a Saga that has no deferred domain-owned business gate."""

    return _advance_project_mutation(
        store, run_id, finalize_run=True, allow_post_commit_gate=False,
    )


def recover_project_mutations(
    store: _ProjectStore,
    *,
    workflow: str,
) -> list[str]:
    recovered = []
    for run in store.db.list_nonterminal_workflow_runs(workflow):
        try:
            complete_project_mutation(store, str(run["id"]))
        except Exception:
            # Keep target/snapshot evidence for a later retry or diagnosis.
            # Unknown concurrent authority must never be overwritten merely to
            # make startup look successful.
            continue
        recovered.append(str(run["id"]))
    return recovered
