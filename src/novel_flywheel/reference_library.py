from __future__ import annotations

import hashlib
import shutil
import uuid
from pathlib import Path

from novel_flywheel.db import Database
from novel_flywheel.local_editorial import ANALYZER, VERSION, analyze_prose


class ReferenceLibrary:
    SOURCE_TYPES = {"paste", "txt", "docx", "pdf", "url"}

    def __init__(self, db: Database, root: Path) -> None:
        self.db = db
        self.root = root.resolve()

    def import_text(self, *, title: str, text: str, source_type: str,
                    source_uri: str | None = None, warnings: list[str] | None = None) -> dict:
        title = title.strip()
        normalized = self._normalize(text)
        if not title or len(title) > 120:
            raise ValueError("Reference title must contain 1-120 characters")
        if source_type not in self.SOURCE_TYPES:
            raise ValueError(f"Unsupported reference source type: {source_type}")
        digest = self._hash(normalized)
        existing = self.db.find_reference_source_by_hash(digest)
        if existing:
            return self.get(existing["id"])
        source_id = uuid.uuid4().hex
        self.db.create_reference_source(source_id, title, source_type, source_uri=source_uri)
        try:
            self._write_version(source_id, normalized, digest)
        except Exception:
            self.db.delete_reference_source(source_id)
            raise
        result = self.get(source_id)
        result["extraction_warnings"] = warnings or []
        return result

    def add_version(self, source_id: str, text: str) -> dict:
        self._validate_id(source_id)
        if self.db.get_reference_source(source_id) is None:
            raise LookupError(f"Reference source not found: {source_id}")
        normalized = self._normalize(text)
        digest = self._hash(normalized)
        for version in self.db.list_reference_versions(source_id):
            if version["content_hash"] == digest:
                return self._public_version(version)
        return self._public_version(self._write_version(source_id, normalized, digest))

    def list(self) -> list[dict]:
        return [self.get(item["id"]) for item in self.db.list_reference_sources()]

    def comparison_sources(self, project_id: str | None = None,
                           character_cap: int = 100_000) -> list[dict[str, str]]:
        del project_id  # Reference storage is global; project adoption filtering can narrow this later.
        result, used, hashes = [], 0, set()
        for source in self.list():
            version = source.get("latest_version")
            if not version:
                continue
            text = self.read_text(source["id"], version["id"])
            digest = self._hash(text)
            if digest in hashes or used >= character_cap:
                continue
            text = text[:character_cap - used]
            result.append({
                "id": f"reference:{source['id']}:{version['id']}",
                "title": source["title"], "text": text,
            })
            hashes.add(digest)
            used += len(text)
        return result

    def get(self, source_id: str) -> dict:
        self._validate_id(source_id)
        source = self.db.get_reference_source(source_id)
        if source is None:
            raise LookupError(f"Reference source not found: {source_id}")
        versions = [self._public_version(item) for item in self.db.list_reference_versions(source_id)]
        return {**source, "latest_version": versions[0] if versions else None, "versions": versions}

    def read_text(self, source_id: str, version_id: str | None = None) -> str:
        source = self.get(source_id)
        versions = source["versions"]
        selected = next((item for item in versions if item["id"] == version_id), None) if version_id else (
            versions[0] if versions else None
        )
        if selected is None:
            raise LookupError("Reference version not found")
        path = self._contained(Path(selected["storage_path"]))
        return path.read_text(encoding="utf-8")

    def delete(self, source_id: str) -> None:
        self._validate_id(source_id)
        with self.db.connect() as connection:
            connection.execute(
                "UPDATE learning_nodes SET status='source_deleted', updated_at=datetime('now') WHERE source_id=?",
                (source_id,),
            )
            connection.execute(
                "UPDATE project_adoptions SET status='review_source_deleted', updated_at=datetime('now') "
                "WHERE node_id IN (SELECT id FROM learning_nodes WHERE source_id=?) AND status='adopted'",
                (source_id,),
            )
        if not self.db.delete_reference_source(source_id):
            raise LookupError(f"Reference source not found: {source_id}")
        directory = self._contained(self.root / source_id)
        if directory.exists():
            shutil.rmtree(directory)

    def analyze(self, source_id: str, version_id: str | None = None) -> dict:
        source = self.get(source_id)
        versions = source["versions"]
        version = next((item for item in versions if item["id"] == version_id), None) if version_id else (
            versions[0] if versions else None
        )
        if version is None:
            raise LookupError("Reference version not found")
        cached = self.db.get_reference_analysis(
            version["id"], ANALYZER, VERSION, version["content_hash"],
        )
        if cached:
            return {**cached, "cached": True}
        result = analyze_prose(self.read_text(source_id, version["id"]))
        saved = self.db.save_reference_analysis(
            uuid.uuid4().hex, source_id, version["id"], ANALYZER, VERSION,
            version["content_hash"], result,
        )
        return {**saved, "cached": False}

    def _write_version(self, source_id: str, text: str, digest: str) -> dict:
        version_id = uuid.uuid4().hex
        directory = self._contained(self.root / source_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = self._contained(directory / f"{version_id}.txt")
        temporary = self._contained(path.with_suffix(".tmp"))
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)
        try:
            return self.db.create_reference_version(
                version_id, source_id, digest, len(text), str(path),
            )
        except Exception:
            path.unlink(missing_ok=True)
            raise

    def _contained(self, path: Path) -> Path:
        resolved = path.resolve()
        if resolved != self.root and self.root not in resolved.parents:
            raise ValueError("Reference path escapes the storage root")
        return resolved

    @staticmethod
    def _normalize(text: str) -> str:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not normalized:
            raise ValueError("Reference text is empty")
        return normalized

    @staticmethod
    def _hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _validate_id(value: str) -> None:
        if not value or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("Invalid reference identifier")

    @staticmethod
    def _public_version(version: dict) -> dict:
        return dict(version)
