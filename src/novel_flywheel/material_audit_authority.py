from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from novel_flywheel.semantic_packets import canonical_sha256
from novel_flywheel.structured_artifacts import StructuredArtifactContract


MATERIAL_AUDIT_PROTOCOL_VERSION = 1


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class MaterialAuditReferenceFileV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    path: str = Field(min_length=1)
    characters: int = Field(ge=0)
    text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class MaterialAuditReferenceChunkV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    path: str = Field(min_length=1)
    chunk_index: int = Field(ge=1)
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_span(self) -> "MaterialAuditReferenceChunkV1":
        if self.end < self.start:
            raise ValueError("material reference chunk span is invalid")
        return self

    @property
    def chunk_id(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


class MaterialAuditReferenceAuthorityV1(BaseModel):
    """Content-addressed complete project-reference manifest.

    Raw material prose remains outside the authority envelope.  Every file and
    every exact span is nevertheless hash-bound, so checkpoint reuse cannot
    silently combine a new reference with an old model receipt.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    version: Literal[MATERIAL_AUDIT_PROTOCOL_VERSION] = (
        MATERIAL_AUDIT_PROTOCOL_VERSION
    )
    files: list[MaterialAuditReferenceFileV1]
    chunks: list[MaterialAuditReferenceChunkV1]
    authority_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_authority(self) -> "MaterialAuditReferenceAuthorityV1":
        payload = self.model_dump(mode="json", exclude={"authority_sha256"})
        if canonical_sha256(payload) != self.authority_sha256:
            raise ValueError("material reference authority hash is stale")
        paths = [item.path for item in self.files]
        if paths != sorted(paths) or len(paths) != len(set(paths)):
            raise ValueError("material reference file order is not canonical")
        file_map = {item.path: item for item in self.files}
        grouped: dict[str, list[MaterialAuditReferenceChunkV1]] = {}
        for chunk in self.chunks:
            source = file_map.get(chunk.path)
            if source is None or source.text_sha256 != chunk.source_sha256:
                raise ValueError("material reference chunk source is stale")
            grouped.setdefault(chunk.path, []).append(chunk)
        for path, source in file_map.items():
            chunks = grouped.get(path, [])
            if source.characters == 0:
                if chunks:
                    raise ValueError("empty material reference has unexpected chunks")
                continue
            if not chunks:
                raise ValueError("material reference chunk coverage is incomplete")
            ordered = sorted(chunks, key=lambda item: item.chunk_index)
            if [item.chunk_index for item in ordered] != list(
                range(1, len(ordered) + 1)
            ):
                raise ValueError("material reference chunk order is invalid")
            cursor = 0
            for chunk in ordered:
                if chunk.start != cursor or chunk.end <= chunk.start:
                    raise ValueError("material reference chunk coverage has a gap")
                cursor = chunk.end
            if cursor != source.characters:
                raise ValueError("material reference chunk coverage is incomplete")
        return self


@dataclass(frozen=True)
class MaterialAuditReferenceBundle:
    authority: MaterialAuditReferenceAuthorityV1
    text_by_chunk_id: Mapping[str, str]

    def text_for(self, chunk: MaterialAuditReferenceChunkV1) -> str:
        text = self.text_by_chunk_id.get(chunk.chunk_id)
        if (
            text is None
            and chunk.path == ".runtime/empty-reference"
            and chunk.start == chunk.end == 0
            and chunk.text_sha256 == _text_sha256("")
        ):
            return ""
        if text is None or _text_sha256(text) != chunk.text_sha256:
            raise ValueError("material reference chunk text is stale")
        return text


class MaterialAuditPacketV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    version: Literal[MATERIAL_AUDIT_PROTOCOL_VERSION] = (
        MATERIAL_AUDIT_PROTOCOL_VERSION
    )
    sequence: int = Field(ge=1)
    manuscript_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reference_authority_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manuscript_window_index: int = Field(ge=1)
    manuscript_start: int = Field(ge=0)
    manuscript_end: int = Field(ge=1)
    manuscript_text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reference_chunk: MaterialAuditReferenceChunkV1

    @model_validator(mode="after")
    def validate_span(self) -> "MaterialAuditPacketV1":
        if self.manuscript_end <= self.manuscript_start:
            raise ValueError("material audit manuscript span is invalid")
        return self

    @property
    def packet_id(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


class MaterialAuditIssueV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    category: str = Field(min_length=1)
    severity: Literal["low", "medium", "high", "critical"]
    evidence: str = Field(min_length=1)
    location: str = Field(min_length=1)
    old_setting: str
    new_setting: str
    action: str = Field(min_length=1)


class MaterialAuditReceiptV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    issues: list[MaterialAuditIssueV1] = Field(default_factory=list)


MATERIAL_AUDIT_STRUCTURED_CONTRACT = StructuredArtifactContract(
    name="material_audit_receipt_v1",
    version=MATERIAL_AUDIT_PROTOCOL_VERSION,
    schema=MaterialAuditReceiptV1.model_json_schema(),
    runtime_authority={
        "manuscript_span": "runtime_owned",
        "reference_span": "runtime_owned",
        "evidence_binding": "descriptive_business_field_preserved",
    },
)


class MaterialAuditCheckpointPayloadV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    version: Literal[MATERIAL_AUDIT_PROTOCOL_VERSION] = (
        MATERIAL_AUDIT_PROTOCOL_VERSION
    )
    packet_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    receipt: MaterialAuditReceiptV1


def _contiguous_spans(text: str, target_characters: int) -> tuple[tuple[int, int], ...]:
    if target_characters < 256:
        raise ValueError("material reference packet target is too small")
    if not text:
        return ()
    spans: list[tuple[int, int]] = []
    start = 0
    while start < len(text):
        wanted = min(len(text), start + target_characters)
        end = wanted
        if wanted < len(text):
            lower = start + max(1, target_characters // 2)
            paragraph = text.rfind("\n\n", lower, wanted + 1)
            if paragraph >= lower:
                end = paragraph + 2
            else:
                punctuation = max(
                    text.rfind(mark, lower, wanted + 1)
                    for mark in ("。", "！", "？", ".", "!", "?")
                )
                if punctuation >= lower:
                    end = punctuation + 1
        if end <= start:
            end = min(len(text), start + target_characters)
        spans.append((start, end))
        start = end
    return tuple(spans)


def build_material_reference_authority(
    project_path: Path, *, target_characters: int,
) -> MaterialAuditReferenceBundle:
    paths = [project_path / "constraints.md"]
    for folder in ("characters", "worldbuilding", "plot"):
        paths.extend(sorted((project_path / folder).rglob("*.md")))
    unique_paths = sorted({
        path for path in paths
        if path.is_file() and "_index.md" not in path.name
    }, key=lambda path: path.relative_to(project_path).as_posix())
    files: list[MaterialAuditReferenceFileV1] = []
    chunks: list[MaterialAuditReferenceChunkV1] = []
    text_by_chunk_id: dict[str, str] = {}
    for path in unique_paths:
        relative = path.relative_to(project_path).as_posix()
        text = path.read_text(encoding="utf-8")
        source_sha256 = _text_sha256(text)
        files.append(MaterialAuditReferenceFileV1(
            path=relative, characters=len(text), text_sha256=source_sha256,
        ))
        for chunk_index, (start, end) in enumerate(
            _contiguous_spans(text, target_characters), 1,
        ):
            chunk_text = text[start:end]
            chunk = MaterialAuditReferenceChunkV1(
                path=relative, chunk_index=chunk_index,
                start=start, end=end, source_sha256=source_sha256,
                text_sha256=_text_sha256(chunk_text),
            )
            chunks.append(chunk)
            text_by_chunk_id[chunk.chunk_id] = chunk_text
    if not chunks:
        synthetic = MaterialAuditReferenceFileV1(
            path=".runtime/empty-reference", characters=0,
            text_sha256=_text_sha256(""),
        )
        files.append(synthetic)
        files.sort(key=lambda item: item.path)
    payload = {
        "version": MATERIAL_AUDIT_PROTOCOL_VERSION,
        "files": [item.model_dump(mode="json") for item in files],
        "chunks": [item.model_dump(mode="json") for item in chunks],
    }
    authority = MaterialAuditReferenceAuthorityV1(
        **payload, authority_sha256=canonical_sha256(payload),
    )
    return MaterialAuditReferenceBundle(
        authority=authority, text_by_chunk_id=text_by_chunk_id,
    )


def build_material_audit_packets(
    bundle: MaterialAuditReferenceBundle,
    manuscript: str,
    windows: Sequence[Mapping[str, Any]],
) -> tuple[MaterialAuditPacketV1, ...]:
    manuscript_sha256 = _text_sha256(manuscript)
    reference_chunks = list(bundle.authority.chunks)
    if not reference_chunks:
        reference_chunks = [MaterialAuditReferenceChunkV1(
            path=".runtime/empty-reference", chunk_index=1,
            start=0, end=0, source_sha256=_text_sha256(""),
            text_sha256=_text_sha256(""),
        )]
    packets: list[MaterialAuditPacketV1] = []
    for window in windows:
        start = int(window["start"])
        end = int(window["end"])
        text = str(window["text"])
        if manuscript[start:end] != text or not text:
            raise ValueError("material audit manuscript window authority is stale")
        for chunk in reference_chunks:
            packets.append(MaterialAuditPacketV1(
                sequence=len(packets) + 1,
                manuscript_sha256=manuscript_sha256,
                reference_authority_sha256=(
                    bundle.authority.authority_sha256
                ),
                manuscript_window_index=int(window["index"]),
                manuscript_start=start,
                manuscript_end=end,
                manuscript_text_sha256=_text_sha256(text),
                reference_chunk=chunk,
            ))
    return tuple(packets)


def material_audit_packet_prompt(
    packet: MaterialAuditPacketV1,
    *, manuscript_text: str,
    reference_text: str,
) -> str:
    if _text_sha256(manuscript_text) != packet.manuscript_text_sha256:
        raise ValueError("material audit manuscript packet text is stale")
    if _text_sha256(reference_text) != packet.reference_chunk.text_sha256:
        raise ValueError("material audit reference packet text is stale")
    return (
        "MATERIAL CONSISTENCY AUDIT PACKET V1. Compare this complete manuscript "
        "window with this exact project-reference span. Return JSON only as "
        "{\"issues\":[...]}. Each issue must contain category, severity "
        "(low|medium|high|critical), evidence, location, old_setting, "
        "new_setting, and action. evidence must be an exact contiguous excerpt "
        "from MANUSCRIPT WINDOW. Report only evidenced contradictions, not style "
        "preferences. Do not rewrite. Runtime will merge all reference spans and "
        "manuscript windows; an empty issue list is valid for this packet.\n\n"
        f"PACKET ID: {packet.packet_id}\n"
        f"REFERENCE FILE: {packet.reference_chunk.path}\n"
        f"REFERENCE SPAN: {packet.reference_chunk.start}-"
        f"{packet.reference_chunk.end}\n"
        f"PROJECT REFERENCE SPAN:\n{reference_text}\n\n"
        f"MANUSCRIPT SPAN: {packet.manuscript_start}-"
        f"{packet.manuscript_end}\n"
        f"MANUSCRIPT WINDOW:\n{manuscript_text}"
    )


def normalize_material_audit_receipt(
    value: object, *, manuscript_text: str,
) -> dict[str, Any] | None:
    try:
        receipt = MaterialAuditReceiptV1.model_validate(value)
    except (TypeError, ValueError):
        return None
    # Existing material-audit business output treats ``evidence`` as a
    # descriptive issue field.  The packet span is Runtime-owned, but this
    # infrastructure migration must not silently narrow accepted reports by
    # turning a previously descriptive quote into a new exact-evidence gate.
    # A future policy change may introduce a separate typed exact-span field.
    if not isinstance(manuscript_text, str):
        return None
    return receipt.model_dump(mode="json")


def material_audit_checkpoint_payload(
    packet: MaterialAuditPacketV1, receipt: Mapping[str, Any],
) -> dict[str, Any]:
    return MaterialAuditCheckpointPayloadV1(
        packet_id=packet.packet_id,
        receipt=MaterialAuditReceiptV1.model_validate(receipt),
    ).model_dump(mode="json")


def validate_material_audit_checkpoint(
    value: object, packet: MaterialAuditPacketV1, *, manuscript_text: str,
) -> dict[str, Any] | None:
    try:
        checkpoint = MaterialAuditCheckpointPayloadV1.model_validate(value)
    except (TypeError, ValueError):
        return None
    if checkpoint.packet_id != packet.packet_id:
        return None
    receipt = checkpoint.receipt.model_dump(mode="json")
    return normalize_material_audit_receipt(
        receipt, manuscript_text=manuscript_text,
    )


def merge_material_audit_receipts(
    receipts: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Stable set union without reinterpreting any issue's business meaning."""

    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for receipt in receipts:
        parsed = MaterialAuditReceiptV1.model_validate(receipt)
        for issue in parsed.issues:
            value = issue.model_dump(mode="json")
            identity = canonical_sha256(value)
            if identity in seen:
                continue
            seen.add(identity)
            merged.append(value)
    return merged
