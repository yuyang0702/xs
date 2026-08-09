from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Callable, Iterable

from markdown_it import MarkdownIt


EventIdExtractor = Callable[[object], list[str]]


@dataclass(frozen=True)
class NarrativeBlock:
    """One exact, non-overlapping Markdown block with narrative ownership."""

    start_line: int
    end_line: int
    start: int
    end: int
    text: str
    kind: str
    explicit_event_ids: tuple[str, ...] = ()
    owner_event_ids: tuple[str, ...] = ()
    ownership: str = "none"

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class NarrativeDocument:
    """Canonical Markdown transport view; the source text remains authority."""

    source: str
    blocks: tuple[NarrativeBlock, ...]

    def event_blocks(self, event_ids: Iterable[str]) -> tuple[NarrativeBlock, ...]:
        requested = {str(value or "").strip().upper() for value in event_ids}
        return tuple(
            block for block in self.blocks
            if requested.intersection(block.owner_event_ids)
        )

    def project_events(self, event_ids: Iterable[str]) -> str:
        selected = self.event_blocks(event_ids)
        return "\n\n".join(block.text.strip() for block in selected).strip()


def _line_offsets(text: str) -> list[int]:
    offsets = [0]
    for index, character in enumerate(text):
        if character == "\n":
            offsets.append(index + 1)
    offsets.append(len(text))
    return offsets


def _top_level_ranges(tokens: list) -> list[tuple[int, int, str]]:
    """Return leaf-most list items plus ordinary top-level Markdown blocks."""
    list_ranges: list[tuple[int, int, str]] = []
    excluded: list[tuple[int, int]] = []
    for token in tokens:
        if token.map is None:
            continue
        start, end = int(token.map[0]), int(token.map[1])
        if token.type == "list_item_open":
            list_ranges.append((start, end, "list_item"))
        elif token.type in {"fence", "code_block", "html_block"}:
            excluded.append((start, end))

    # Keep outer list items as the independent transport units.  Their exact
    # range includes nested bullets, while keeping a child as well would
    # duplicate prose and can detach the parent's explicit event identity.
    leaves: list[tuple[int, int, str]] = []
    for item in list_ranges:
        start, end, _kind = item
        if any(
            other_start <= start and other_end >= end
            and (other_start, other_end) != (start, end)
            for other_start, other_end, _ in list_ranges
        ):
            continue
        leaves.append(item)

    ranges = list(leaves)
    for token in tokens:
        if token.map is None or token.type not in {"heading_open", "paragraph_open"}:
            continue
        start, end = int(token.map[0]), int(token.map[1])
        if any(owner_start <= start < owner_end for owner_start, owner_end, _ in list_ranges):
            continue
        if any(skip_start <= start < skip_end for skip_start, skip_end in excluded):
            continue
        ranges.append((start, end, "heading" if token.type == "heading_open" else "paragraph"))
    return sorted(set(ranges), key=lambda item: (item[0], item[1], item[2]))


def parse_narrative_document(
    value: object, *, event_id_extractor: EventIdExtractor,
) -> NarrativeDocument:
    """Parse Markdown once and bind unlabelled continuation blocks by order.

    Ownership is presentation-independent: inside a sequence of narrative
    blocks, an unlabelled block inherits the preceding explicit event until a
    later explicit event starts.  Fenced examples and HTML blocks never gain
    narrative ownership.
    """
    source = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    if not source:
        return NarrativeDocument(source="", blocks=())
    tokens = MarkdownIt("commonmark").parse(source)
    offsets = _line_offsets(source)
    raw_blocks: list[NarrativeBlock] = []
    for start_line, end_line, kind in _top_level_ranges(tokens):
        start = offsets[min(start_line, len(offsets) - 1)]
        end = offsets[min(end_line, len(offsets) - 1)]
        text = source[start:end].strip("\n")
        if not text.strip():
            continue
        event_ids = tuple(dict.fromkeys(
            str(item or "").strip().upper()
            for item in event_id_extractor(text)
            if str(item or "").strip()
        ))
        raw_blocks.append(NarrativeBlock(
            start_line=start_line,
            end_line=end_line,
            start=start,
            end=end,
            text=text,
            kind=kind,
            explicit_event_ids=event_ids,
            owner_event_ids=event_ids,
            ownership="explicit" if event_ids else "none",
        ))

    result: list[NarrativeBlock] = []
    previous_event_ids: tuple[str, ...] = ()
    for block in raw_blocks:
        owners = block.explicit_event_ids
        ownership = block.ownership
        if owners:
            previous_event_ids = owners
        elif block.kind in {"list_item", "paragraph"} and previous_event_ids:
            owners = previous_event_ids
            ownership = "inherited"
        elif block.kind == "heading":
            previous_event_ids = ()
        result.append(NarrativeBlock(
            start_line=block.start_line,
            end_line=block.end_line,
            start=block.start,
            end=block.end,
            text=block.text,
            kind=block.kind,
            explicit_event_ids=block.explicit_event_ids,
            owner_event_ids=owners,
            ownership=ownership,
        ))
    return NarrativeDocument(source=source, blocks=tuple(result))
