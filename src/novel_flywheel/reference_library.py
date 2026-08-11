from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from novel_flywheel.db import Database, WIZARD_MUTATION_LOCK
from novel_flywheel.local_editorial import ANALYZER, VERSION, analyze_prose
from novel_flywheel.originality import OriginalitySourceChunkV1
from novel_flywheel.reference_classification import CONTENT_TYPES, classify_reference
from novel_flywheel.reference_policy import build_classification_snapshot
from novel_flywheel.reference_distillation import source_use_mode


@dataclass(frozen=True)
class _ReferenceVersionForOriginality:
    source_id: str
    title: str
    version_id: str
    version_sha256: str
    path: Path
    character_count: int
    use_mode: str


class _OriginalityChunkStream(Iterable[OriginalitySourceChunkV1]):
    """Re-iterable, bounded source reader used by all local originality gates."""

    def __init__(
        self, versions: tuple[_ReferenceVersionForOriginality, ...], *,
        chunk_characters: int, overlap_characters: int,
    ) -> None:
        self._versions = versions
        self._chunk_characters = chunk_characters
        self._overlap_characters = overlap_characters

    def __iter__(self) -> Iterator[OriginalitySourceChunkV1]:
        step = self._chunk_characters - self._overlap_characters
        for version in self._versions:
            if version.character_count <= self._chunk_characters:
                chunk_count = 1
            else:
                remaining = version.character_count - self._chunk_characters
                chunk_count = 1 + (remaining + step - 1) // step
            with version.path.open("r", encoding="utf-8") as handle:
                text = handle.read(self._chunk_characters)
                digest = hashlib.sha256()
                digest.update(text.encode("utf-8"))
                start = 0
                index = 0
                while text:
                    yield OriginalitySourceChunkV1(
                        id=(
                            f"reference:{version.source_id}:"
                            f"{version.version_id}"
                        ),
                        title=version.title,
                        text=text,
                        source_start=start,
                        source_end=start + len(text),
                        chunk_index=index,
                        chunk_count=chunk_count,
                        version_id=version.version_id,
                        version_sha256=version.version_sha256,
                        use_mode=version.use_mode,
                    )
                    next_text = handle.read(step)
                    if not next_text:
                        break
                    digest.update(next_text.encode("utf-8"))
                    start += len(text) - self._overlap_characters
                    text = text[-self._overlap_characters:] + next_text
                    index += 1
                if digest.hexdigest() != version.version_sha256:
                    raise ValueError("reference version content does not match its provenance hash")


class ReferenceLibrary:
    SOURCE_TYPES = {"paste", "txt", "docx", "pdf", "url"}

    def __init__(self, db: Database, root: Path) -> None:
        self.db = db
        self.root = root.resolve()

    def import_text(self, *, title: str, text: str, source_type: str,
                    source_uri: str | None = None, warnings: list[str] | None = None,
                    platform: str | None = None, content_type: str | None = None,
                    project_id: str | None = None) -> dict:
        with WIZARD_MUTATION_LOCK:
            return self._import_text(
                title=title, text=text, source_type=source_type,
                source_uri=source_uri, warnings=warnings, platform=platform,
                content_type=content_type, project_id=project_id,
            )

    def _import_text(self, *, title: str, text: str, source_type: str,
                    source_uri: str | None = None, warnings: list[str] | None = None,
                    platform: str | None = None, content_type: str | None = None,
                    project_id: str | None = None) -> dict:
        title = title.strip()
        normalized = self._normalize(text)
        if not title or len(title) > 120:
            raise ValueError("Reference title must contain 1-120 characters")
        if source_type not in self.SOURCE_TYPES:
            raise ValueError(f"Unsupported reference source type: {source_type}")
        recommendation = classify_reference(title, normalized, source_uri)
        selected_type = content_type or str(recommendation["content_type"])
        if selected_type not in CONTENT_TYPES:
            raise ValueError(f"Unsupported reference content type: {selected_type}")
        selected_platform = (platform if platform is not None else str(recommendation["platform"])).strip() or None
        classification = build_classification_snapshot(
            recommendation, platform=selected_platform, content_type=selected_type,
            user_selected=platform is not None or content_type is not None,
        )
        digest = self._hash(normalized)
        existing = self.db.find_reference_source_by_hash(digest)
        if existing:
            return self.get(existing["id"])
        source_id = uuid.uuid4().hex
        self.db.create_reference_source(
            source_id, title, source_type, source_uri=source_uri, platform=selected_platform,
            content_type=selected_type, project_id=project_id, classification=classification,
        )
        try:
            self._write_version(source_id, normalized, digest)
        except Exception:
            self.db.delete_reference_source(source_id)
            raise
        result = self.get(source_id)
        result["recommendation"] = recommendation
        result["extraction_warnings"] = warnings or []
        return result

    def update_metadata(
        self, source_id: str, *, platform: str | None, content_type: str, project_id: str | None,
    ) -> dict:
        with WIZARD_MUTATION_LOCK:
            return self._update_metadata(
                source_id, platform=platform, content_type=content_type, project_id=project_id,
            )

    def _update_metadata(
        self, source_id: str, *, platform: str | None, content_type: str, project_id: str | None,
    ) -> dict:
        self._validate_id(source_id)
        if content_type not in CONTENT_TYPES:
            raise ValueError(f"Unsupported reference content type: {content_type}")
        normalized_platform = (platform or "").strip() or None
        classification = build_classification_snapshot(
            {"platform": normalized_platform or "", "content_type": content_type, "confidence": 1.0},
            platform=normalized_platform, content_type=content_type, user_selected=True,
        )
        if not self.db.update_reference_source_metadata(
            source_id, normalized_platform, content_type, project_id, classification,
        ):
            raise LookupError(f"Reference source not found: {source_id}")
        return self.get(source_id)

    def add_version(self, source_id: str, text: str) -> dict:
        with WIZARD_MUTATION_LOCK:
            return self._add_version(source_id, text)

    def _add_version(self, source_id: str, text: str) -> dict:
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

    def _visible_originality_versions(
        self, project_id: str | None,
    ) -> list[dict]:
        scope = (
            "source.project_id IS NULL"
            if project_id is None
            else "(source.project_id IS NULL OR source.project_id=?)"
        )
        arguments = () if project_id is None else (project_id,)
        with self.db.connect() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT source.id AS source_id,source.title,source.platform,"
                "source.content_type,source.project_id,source.classification_json,"
                "source.status,version.id AS version_id,version.version,"
                "version.content_hash,version.character_count,version.storage_path "
                "FROM reference_sources source JOIN reference_versions version "
                "ON version.source_id=source.id "
                "WHERE source.content_type<>'platform_rule' AND " + scope + " "
                "ORDER BY source.id,version.version,version.id",
                arguments,
            )]

    def reference_corpus_authority(
        self, project_id: str | None = None,
    ) -> dict:
        """Return a text-free, content-addressed originality corpus manifest."""

        visible_versions = self._visible_originality_versions(project_id)
        grouped: dict[str, dict] = {}
        for row in visible_versions:
            source_id = str(row["source_id"])
            source = grouped.get(source_id)
            if source is None:
                try:
                    raw_classification = json.loads(
                        row.get("classification_json") or "{}",
                    )
                except (TypeError, ValueError):
                    raw_classification = {}
                if not isinstance(raw_classification, dict):
                    raw_classification = {}
                content_type = str(row.get("content_type") or "reference_work")
                source = {
                    "source_id": source_id,
                    "project_scope": str(row.get("project_id") or "global"),
                    "status": str(row.get("status") or "active"),
                    "use_mode": source_use_mode(content_type).value,
                    "classification": {
                        **raw_classification,
                        "platform": str(row.get("platform") or ""),
                        "content_type": content_type,
                    },
                    "versions": [],
                }
                grouped[source_id] = source
            source["versions"].append({
                "version_id": str(row["version_id"]),
                "version": int(row["version"]),
                "content_sha256": str(row["content_hash"]),
            })
        manifest = {
            "version": 1,
            "requested_project_scope": str(project_id or "global"),
            "sources": list(grouped.values()),
        }
        encoded = json.dumps(
            manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        return {
            "version": 1,
            "sha256": hashlib.sha256(encoded).hexdigest(),
            "manifest": manifest,
            "_visible_versions": tuple(dict(row) for row in visible_versions),
        }

    def comparison_sources(
        self, project_id: str | None = None, *,
        chunk_characters: int = 32_768,
        overlap_characters: int = 1_024,
        authority: dict | None = None,
    ) -> Iterable[OriginalitySourceChunkV1]:
        """Stream every distinct eligible version as bounded overlapping chunks.

        The overlap is wider than the semantic review window, so literal and
        semantic evidence crossing a chunk boundary remains discoverable. No
        prefix is dropped and only one source chunk is resident at a time.
        """

        if chunk_characters < 1_024:
            raise ValueError("originality chunks must contain at least 1024 characters")
        if overlap_characters < 480 or overlap_characters >= chunk_characters:
            raise ValueError(
                "originality chunk overlap must preserve a complete semantic window",
            )
        if authority is not None:
            expected_scope = str(project_id or "global")
            manifest = authority.get("manifest") or {}
            if manifest.get("requested_project_scope") != expected_scope:
                raise ValueError("reference corpus authority scope does not match the scan")
            visible_rows = [dict(row) for row in authority.get("_visible_versions") or ()]
        else:
            visible_rows = self._visible_originality_versions(project_id)
        versions: list[_ReferenceVersionForOriginality] = []
        for row in visible_rows:
            content_type = str(row.get("content_type") or "reference_work")
            versions.append(_ReferenceVersionForOriginality(
                source_id=str(row["source_id"]),
                title=str(row["title"]),
                version_id=str(row["version_id"]),
                version_sha256=str(row["content_hash"]),
                path=self._contained(Path(str(row["storage_path"]))),
                character_count=int(row["character_count"]),
                use_mode=source_use_mode(content_type).value,
            ))
        return _OriginalityChunkStream(
            tuple(versions), chunk_characters=chunk_characters,
            overlap_characters=overlap_characters,
        )

    def platform_rules(self, platform: str | None) -> list[dict[str, str]]:
        normalized = (platform or "").strip().lower()
        if not normalized:
            return []
        result = []
        for source in self.list():
            if source.get("content_type") != "platform_rule":
                continue
            if (source.get("platform") or "").strip().lower() != normalized:
                continue
            result.append({
                "id": source["id"], "title": source["title"],
                "text": self.read_text(source["id"])[:20_000],
            })
        return result

    def get(self, source_id: str) -> dict:
        self._validate_id(source_id)
        source = self.db.get_reference_source(source_id)
        if source is None:
            raise LookupError(f"Reference source not found: {source_id}")
        versions = [self._public_version(item) for item in self.db.list_reference_versions(source_id)]
        raw = source.pop("classification_json", None)
        try:
            classification = __import__("json").loads(raw) if raw else {}
        except (TypeError, ValueError):
            classification = {}
        classification = {
            "platform": source.get("platform") or "",
            "content_type": source.get("content_type") or "reference_work",
            **classification,
        }
        return {**source, "classification": classification,
                "latest_version": versions[0] if versions else None, "versions": versions}

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
        with WIZARD_MUTATION_LOCK:
            self._delete(source_id)

    def _delete(self, source_id: str) -> None:
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
