from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import math
import re
import unicodedata
from typing import Any, Iterable, Mapping, Protocol, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SemanticEncoder(Protocol):
    def encode(self, texts: list[str]) -> Sequence[Sequence[float]]: ...


class OriginalityFindingV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    finding_type: str
    source_id: str
    severity: str
    manuscript_start: int = Field(ge=0)
    manuscript_end: int = Field(ge=0)
    source_start: int = Field(ge=0)
    source_end: int = Field(ge=0)
    score: float = Field(ge=0, le=1)
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    metadata: dict[str, Any] = Field(default_factory=dict)


class OriginalityReportV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int = 1
    findings: list[OriginalityFindingV1]
    source_ids: list[str]
    layers: list[str]
    # The engine never searches the public web. Callers supply every eligible
    # version from the project's local corpus explicitly.
    scope: str = "local_corpus_only"


class OriginalitySourceChunkV1(BaseModel):
    """One bounded, version-bound source view with absolute character offsets."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    text: str
    source_start: int = Field(ge=0)
    source_end: int = Field(ge=0)
    chunk_index: int = Field(ge=0)
    chunk_count: int = Field(ge=1)
    version_id: str | None = None
    version_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    title: str = ""
    use_mode: str | None = None
    events: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_range(self) -> "OriginalitySourceChunkV1":
        if self.source_end - self.source_start != len(self.text):
            raise ValueError("source chunk range does not match its text length")
        if self.chunk_index >= self.chunk_count:
            raise ValueError("source chunk index exceeds its declared chunk count")
        return self

    def get(self, key: str, default: Any = None) -> Any:
        """Keep legacy read-only mapping consumers compatible during migration."""

        return getattr(self, key, default)


def _source_chunk(
    value: OriginalitySourceChunkV1 | Mapping[str, Any],
) -> OriginalitySourceChunkV1:
    if isinstance(value, OriginalitySourceChunkV1):
        return value
    text = str(value.get("text") or "")
    start = int(value.get("source_start") or 0)
    raw_end = value.get("source_end")
    return OriginalitySourceChunkV1.model_validate({
        "id": str(value.get("id") or "unknown"),
        "text": text,
        "source_start": start,
        "source_end": int(raw_end) if raw_end is not None else start + len(text),
        "chunk_index": int(value.get("chunk_index") or 0),
        "chunk_count": int(value.get("chunk_count") or 1),
        "version_id": value.get("version_id"),
        "version_sha256": value.get("version_sha256"),
        "title": value.get("title") or "",
        "use_mode": value.get("use_mode"),
        "events": value.get("events") or [],
    })


def _chunk_provenance(chunk: OriginalitySourceChunkV1) -> dict[str, Any]:
    result: dict[str, Any] = {
        "source_chunk_start": chunk.source_start,
        "source_chunk_end": chunk.source_end,
        "source_chunk_index": chunk.chunk_index,
        "source_chunk_count": chunk.chunk_count,
    }
    if chunk.version_id:
        result["source_version_id"] = chunk.version_id
    if chunk.version_sha256:
        result["source_version_sha256"] = chunk.version_sha256
    return result


@dataclass(frozen=True)
class _Fingerprint:
    value: int
    start: int
    end: int


def _normalized_with_offsets(text: str) -> tuple[str, list[int]]:
    characters: list[str] = []
    offsets: list[int] = []
    for index, raw in enumerate(text):
        normalized = unicodedata.normalize("NFKC", raw).casefold()
        for character in normalized:
            if character.isalnum() or "\u3400" <= character <= "\u9fff":
                characters.append(character)
                offsets.append(index)
    return "".join(characters), offsets


def winnowing_fingerprints(
    text: str, *, k: int = 13, window: int = 8,
) -> list[_Fingerprint]:
    """Schleimer-style rightmost-minimum fingerprints with source offsets."""

    normalized, offsets = _normalized_with_offsets(text)
    if len(normalized) < k:
        return []
    hashes = [int.from_bytes(hashlib.blake2b(
        normalized[index:index + k].encode("utf-8"), digest_size=8,
    ).digest(), "big") for index in range(len(normalized) - k + 1)]
    selected: list[int] = []
    if len(hashes) <= window:
        # The normal guarantee threshold is k + window - 1. For a document
        # shorter than one complete window, retaining every k-gram avoids a
        # short-scene false negative while remaining strictly bounded.
        selected = list(range(len(hashes)))
    else:
        previous = -1
        for start in range(len(hashes) - window + 1):
            index = min(
                range(start, start + window),
                key=lambda candidate: (hashes[candidate], -candidate),
            )
            if index != previous:
                selected.append(index)
                previous = index
    return [_Fingerprint(
        hashes[index], offsets[index], offsets[min(index + k - 1, len(offsets) - 1)] + 1,
    ) for index in selected]


def _vector(text: str) -> Counter[str]:
    normalized, _offsets = _normalized_with_offsets(text)
    grams: Counter[str] = Counter()
    for size in (2, 3, 4):
        grams.update(
            normalized[index:index + size]
            for index in range(max(0, len(normalized) - size + 1))
        )
    return grams


def _cosine(left: Counter[str], right: Counter[str]) -> float:
    if not left or not right:
        return 0.0
    shared = left.keys() & right.keys()
    numerator = sum(left[key] * right[key] for key in shared)
    denominator = math.sqrt(sum(value * value for value in left.values())) * math.sqrt(
        sum(value * value for value in right.values())
    )
    return numerator / denominator if denominator else 0.0


def _dense_cosine(left: list[float], right: list[float]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    denominator = math.sqrt(sum(value * value for value in left)) * math.sqrt(
        sum(value * value for value in right)
    )
    if not denominator:
        return 0.0
    return max(0.0, min(1.0, numerator / denominator))


def _windows(text: str, *, size: int = 480, step: int = 360) -> list[tuple[int, int, str]]:
    if len(text) <= size:
        return [(0, len(text), text)] if text else []
    result = []
    for start in range(0, len(text), step):
        end = min(len(text), start + size)
        result.append((start, end, text[start:end]))
        if end == len(text):
            break
    return result


def _evidence_hash(
    finding_type: str, source_id: str, manuscript_span: tuple[int, int],
    source_span: tuple[int, int],
) -> str:
    return hashlib.sha256(
        f"{finding_type}\0{source_id}\0{manuscript_span}\0{source_span}".encode("utf-8"),
    ).hexdigest()


class OriginalityEngine:
    """Three independent gates: literal, semantic candidate, event-chain."""

    def __init__(
        self, *, semantic_threshold: float = 0.72,
        encoder: SemanticEncoder | None = None,
    ) -> None:
        self.semantic_threshold = semantic_threshold
        self.encoder = encoder

    def scan(
        self, manuscript: str,
        sources: Iterable[OriginalitySourceChunkV1 | Mapping[str, Any]], *,
        manuscript_events: Iterable[dict[str, Any]] = (),
    ) -> OriginalityReportV1:
        findings: list[OriginalityFindingV1] = []
        source_ids: list[str] = []
        manuscript_fingerprints = winnowing_fingerprints(manuscript)
        by_hash: dict[int, list[_Fingerprint]] = defaultdict(list)
        for fingerprint in manuscript_fingerprints:
            by_hash[fingerprint.value].append(fingerprint)
        manuscript_windows = _windows(manuscript)
        manuscript_vectors = [_vector(value) for _start, _end, value in manuscript_windows]
        encoded_manuscript: list[list[float]] = []
        if self.encoder and manuscript_windows:
            raw_embeddings = self.encoder.encode([
                value for _start, _end, value in manuscript_windows
            ])
            if len(raw_embeddings) != len(manuscript_windows):
                raise ValueError("semantic encoder returned an unexpected embedding count")
            encoded_manuscript = [
                [float(value) for value in vector]
                for vector in raw_embeddings
            ]
        manuscript_event_signatures = _event_signatures(manuscript_events)

        for raw_source in sources:
            source = _source_chunk(raw_source)
            source_id = source.id
            source_ids.append(source_id)
            source_text = source.text
            provenance = _chunk_provenance(source)
            findings.extend(self._literal_findings(
                source_id, source_text, by_hash,
                source_offset=source.source_start, provenance=provenance,
            ))
            findings.extend(self._semantic_findings(
                source_id, source_text, manuscript_windows, manuscript_vectors,
                encoded_manuscript=encoded_manuscript,
                source_offset=source.source_start, provenance=provenance,
            ))
            findings.extend(self._event_findings(
                source_id, manuscript_event_signatures,
                _event_signatures(source.events),
            ))
        deduplicated = {
            (
                item.finding_type, item.source_id, item.manuscript_start,
                item.manuscript_end, item.source_start, item.source_end,
            ): item for item in findings
        }
        return OriginalityReportV1(
            findings=sorted(
                deduplicated.values(),
                key=lambda item: (
                    item.manuscript_start, item.source_id, item.finding_type,
                ),
            ),
            source_ids=list(dict.fromkeys(source_ids)),
            layers=["winnowing_v1", "semantic_windows_v1", "event_chain_v1"],
        )

    @staticmethod
    def _literal_findings(
        source_id: str, source_text: str,
        manuscript_by_hash: dict[int, list[_Fingerprint]],
        *, source_offset: int = 0,
        provenance: Mapping[str, Any] | None = None,
    ) -> list[OriginalityFindingV1]:
        source_fingerprints = winnowing_fingerprints(source_text)
        matches: list[tuple[_Fingerprint, _Fingerprint]] = []
        for right in source_fingerprints:
            for left in manuscript_by_hash.get(right.value, []):
                matches.append((left, right))
        matches.sort(key=lambda pair: (pair[0].start, pair[1].start))
        groups: list[list[tuple[_Fingerprint, _Fingerprint]]] = []
        for pair in matches:
            if not groups or (
                pair[0].start - groups[-1][-1][0].end > 64
                or pair[1].start - groups[-1][-1][1].end > 64
            ):
                groups.append([pair])
            else:
                groups[-1].append(pair)
        result = []
        for group in groups:
            # A selected fingerprint already proves an exact k-character span.
            # Requiring three fingerprints silently misses short scenes even
            # though the winnowing guarantee has been satisfied.
            if not group:
                continue
            m_span = (group[0][0].start, group[-1][0].end)
            s_span = (
                source_offset + group[0][1].start,
                source_offset + group[-1][1].end,
            )
            result.append(OriginalityFindingV1(
                finding_type="literal_winnowing",
                source_id=source_id, severity="hard",
                manuscript_start=m_span[0], manuscript_end=m_span[1],
                source_start=s_span[0], source_end=s_span[1], score=1.0,
                evidence_sha256=_evidence_hash(
                    "literal_winnowing", source_id, m_span, s_span,
                ),
                metadata={
                    "fingerprint_count": len(group),
                    **dict(provenance or {}),
                },
            ))
        return result

    def _semantic_findings(
        self, source_id: str, source_text: str,
        manuscript_windows: list[tuple[int, int, str]],
        manuscript_vectors: list[Counter[str]],
        *, encoded_manuscript: list[list[float]] | None = None,
        source_offset: int = 0,
        provenance: Mapping[str, Any] | None = None,
    ) -> list[OriginalityFindingV1]:
        source_windows = _windows(source_text)
        source_vectors = [_vector(value) for _start, _end, value in source_windows]
        encoded_source: list[list[float]] = []
        if self.encoder and manuscript_windows and source_windows:
            texts = [value for _start, _end, value in source_windows]
            raw_embeddings = self.encoder.encode(texts)
            if len(raw_embeddings) != len(source_windows):
                raise ValueError("semantic encoder returned an unexpected embedding count")
            encoded_source = [
                [float(value) for value in vector]
                for vector in raw_embeddings
            ]
        result = []
        for left_index, (m_start, m_end, _m_text) in enumerate(manuscript_windows):
            best: tuple[float, int] = (0.0, -1)
            for right_index, vector in enumerate(source_vectors):
                lexical_score = _cosine(manuscript_vectors[left_index], vector)
                semantic_score = (
                    _dense_cosine(
                        encoded_manuscript[left_index], encoded_source[right_index],
                    )
                    if encoded_manuscript else 0.0
                )
                score = max(lexical_score, semantic_score)
                if score > best[0]:
                    best = score, right_index
            if best[0] < self.semantic_threshold or best[1] < 0:
                continue
            relative_start, relative_end, _source = source_windows[best[1]]
            s_start = source_offset + relative_start
            s_end = source_offset + relative_end
            result.append(OriginalityFindingV1(
                finding_type="semantic_candidate",
                source_id=source_id,
                severity="review" if best[0] < 0.9 else "hard",
                manuscript_start=m_start, manuscript_end=m_end,
                source_start=s_start, source_end=s_end,
                score=round(best[0], 6),
                evidence_sha256=_evidence_hash(
                    "semantic_candidate", source_id,
                    (m_start, m_end), (s_start, s_end),
                ),
                metadata={
                    "requires_model_review": True,
                    "candidate_method": (
                        "semantic_encoder" if encoded_manuscript else "character_ngrams"
                    ),
                    **dict(provenance or {}),
                },
            ))
        return result

    @staticmethod
    def _event_findings(
        source_id: str, manuscript: list[str], source: list[str],
    ) -> list[OriginalityFindingV1]:
        if len(manuscript) < 3 or len(source) < 3:
            return []
        source_triples = {
            tuple(source[index:index + 3]): index
            for index in range(len(source) - 2)
        }
        result = []
        for index in range(len(manuscript) - 2):
            triple = tuple(manuscript[index:index + 3])
            if triple not in source_triples:
                continue
            source_index = source_triples[triple]
            result.append(OriginalityFindingV1(
                finding_type="event_chain",
                source_id=source_id, severity="review",
                manuscript_start=index, manuscript_end=index + 3,
                source_start=source_index, source_end=source_index + 3,
                score=1.0,
                evidence_sha256=_evidence_hash(
                    "event_chain", source_id, (index, index + 3),
                    (source_index, source_index + 3),
                ),
                metadata={"unit": "event_index", "length": 3},
            ))
        return result


def _event_signatures(events: Iterable[dict[str, Any]]) -> list[str]:
    signatures = []
    for event in events:
        signature = str(event.get("signature") or "").strip().casefold()
        if not signature:
            predicate = str(event.get("predicate") or event.get("action") or "").strip()
            arguments = event.get("arguments") or []
            argument_values = [
                str(item.get("text") if isinstance(item, dict) else item).strip()
                for item in arguments
            ]
            signature = "|".join([predicate, *argument_values]).casefold()
        if signature:
            signatures.append(signature)
    return signatures


def affected_segments(
    report: OriginalityReportV1,
    segment_ranges: Iterable[tuple[int, int, int]],
    *, severities: tuple[str, ...] = ("hard",),
) -> list[int]:
    """Return segments touched by the requested evidence severity classes.

    Review-only semantic candidates are deliberately excluded by default: they
    require adjudication and must not cause an automatic prose rewrite merely
    because a broad comparison window overlaps a segment boundary.
    """

    result = set()
    for finding in report.findings:
        if finding.severity not in severities:
            continue
        for segment, start, end in segment_ranges:
            if finding.manuscript_start < end and finding.manuscript_end > start:
                result.add(segment)
    return sorted(result)
