import hashlib

import pytest

from novel_flywheel.storage import (
    ProjectSnapshot,
    atomic_write,
    atomic_write_bytes,
    project_snapshot_transaction,
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_atomic_write_preserves_original_when_replace_fails(tmp_path) -> None:
    target = tmp_path / "chapter.md"
    target.write_text("original", encoding="utf-8")

    def fail_replace(source, destination):
        raise OSError("disk failure")

    with pytest.raises(OSError, match="disk failure"):
        atomic_write(target, "new text", replace=fail_replace)

    assert target.read_text(encoding="utf-8") == "original"
    assert list(tmp_path.glob("*.tmp")) == []


def test_atomic_write_bytes_preserves_exact_newlines_and_rolls_back_replace_failure(
    tmp_path,
) -> None:
    target = tmp_path / "authority.bin"
    target.write_bytes(b"old\r\nbytes")
    atomic_write_bytes(target, b"new\nbytes\x00")
    assert target.read_bytes() == b"new\nbytes\x00"

    def fail_replace(source, destination):
        raise OSError("byte replace failure")

    with pytest.raises(OSError, match="byte replace failure"):
        atomic_write_bytes(target, b"uncommitted", replace=fail_replace)
    assert target.read_bytes() == b"new\nbytes\x00"
    assert list(tmp_path.glob("*.tmp")) == []


def test_snapshot_restores_changed_and_deleted_files(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    chapter = project / "chapter.md"
    canon = project / "canon.json"
    chapter.write_text("before", encoding="utf-8")
    canon.write_text("{}", encoding="utf-8")
    before = {chapter: digest(chapter), canon: digest(canon)}

    snapshot = ProjectSnapshot.create(project, tmp_path / "snapshots" / "run-1", [chapter, canon])
    chapter.write_text("after", encoding="utf-8")
    canon.unlink()
    snapshot.restore()

    assert {path: digest(path) for path in before} == before


def test_snapshot_restore_ignores_missing_targets_and_existing_directories(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    missing = project / "missing" / "chapter.md"
    snapshot = ProjectSnapshot.create(
        project, tmp_path / "snapshots" / "run-missing", [missing],
    )

    # The target was never a file, and a later run may create a directory at
    # the same path. Recovery must stay idempotent and must not remove trees.
    missing.mkdir(parents=True)
    missing.joinpath("keep.txt").write_text("keep", encoding="utf-8")
    snapshot.restore()

    assert missing.is_dir()
    assert missing.joinpath("keep.txt").read_text(encoding="utf-8") == "keep"


def test_snapshot_manifest_is_written_atomically(tmp_path, monkeypatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    chapter = project / "chapter.md"
    chapter.write_text("before", encoding="utf-8")
    calls = []
    original = __import__(
        "novel_flywheel.storage", fromlist=["atomic_write"],
    ).atomic_write

    def tracked(path, content, *args, **kwargs):
        calls.append(path)
        return original(path, content, *args, **kwargs)

    monkeypatch.setattr("novel_flywheel.storage.atomic_write", tracked)

    snapshot = ProjectSnapshot.create(
        project, project / "snapshots" / "run-atomic", [chapter],
    )

    assert calls == [snapshot.snapshot_root / "manifest.json"]


def test_snapshot_discard_is_idempotent(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    chapter = project / "chapter.md"
    chapter.write_text("before", encoding="utf-8")
    snapshot = ProjectSnapshot.create(
        project, project / "snapshots" / "run-discard", [chapter],
    )

    snapshot.discard()
    snapshot.discard()

    assert not snapshot.snapshot_root.exists()


def test_project_snapshot_transaction_commits_and_discards_snapshot(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    chapter = project / "chapter.md"
    chapter.write_text("before", encoding="utf-8")
    snapshot_root = project / "snapshots" / "transaction-success"

    with project_snapshot_transaction(project, snapshot_root, [chapter]):
        chapter.write_text("after", encoding="utf-8")

    assert chapter.read_text(encoding="utf-8") == "after"
    assert not snapshot_root.exists()


def test_project_snapshot_transaction_rolls_back_base_exception(tmp_path) -> None:
    class SimulatedCancellation(BaseException):
        pass

    project = tmp_path / "project"
    project.mkdir()
    chapter = project / "chapter.md"
    chapter.write_text("before", encoding="utf-8")
    snapshot_root = project / "snapshots" / "transaction-cancelled"

    with pytest.raises(SimulatedCancellation):
        with project_snapshot_transaction(project, snapshot_root, [chapter]):
            chapter.write_text("partial", encoding="utf-8")
            raise SimulatedCancellation

    assert chapter.read_text(encoding="utf-8") == "before"
    assert not snapshot_root.exists()


def test_project_snapshot_transaction_preserves_snapshot_when_rollback_fails(
    tmp_path, monkeypatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    chapter = project / "chapter.md"
    chapter.write_text("before", encoding="utf-8")
    snapshot_root = project / "snapshots" / "transaction-rollback-failed"

    def fail_restore(_snapshot):
        raise RuntimeError("simulated rollback failure")

    monkeypatch.setattr(ProjectSnapshot, "restore", fail_restore)

    with pytest.raises(RuntimeError, match="simulated rollback failure"):
        with project_snapshot_transaction(project, snapshot_root, [chapter]):
            chapter.write_text("partial", encoding="utf-8")
            raise ValueError("mutation failed")

    assert chapter.read_text(encoding="utf-8") == "partial"
    assert snapshot_root.is_dir()
    assert (snapshot_root / "manifest.json").is_file()
