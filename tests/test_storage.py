import hashlib

import pytest

from novel_flywheel.storage import ProjectSnapshot, atomic_write


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
