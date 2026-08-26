"""Deterministic, source-faithful Skill context compiler for shadow evidence.

The module has no Provider, model, network, project-state, or prompt-authority
dependency.  Its output is non-authoritative until a later, separately approved
cutover.  The production workflow exposes only an optional observer seam.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Iterable, Mapping, Sequence

from novel_flywheel.context_policy import estimate_input_tokens


INDEX_SCHEMA = "SkillSectionIndexV1"
INDEX_VERSION = 1
COMPILER_VERSION = "verbatim-selective-skill-compiler-shadow-v1"
RESOLVER_VERSION = "existing-stage-skill-resolver-v1"
SELECTOR_POLICY_VERSION = "selective-section-selector-v1"
RENDER_POLICY_VERSION = "verbatim-section-renderer-v1"
BUDGET_POLICY_VERSION = "semantic-budget-v1"

DEMAND_CLASSES = frozenset({
    "character-heavy",
    "world-heavy",
    "conflict-pacing-heavy",
    "setup-payoff-heavy",
    "mixed",
})
SELECTION_CLASSES = frozenset({
    "ALWAYS_ON_STAGE_CORE",
    "DEMAND_SPECIFIC",
    "CONTRACT_SPECIFIC",
    "OPTIONAL_SUPPORT",
    "EXCLUDED_WRONG_LAYER",
})
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _canonical_text(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")


class SkillCompilerError(ValueError):
    """Typed base failure for deterministic shadow compilation."""


class SectionIndexError(SkillCompilerError):
    """The checked-in index no longer exactly names its source bytes."""


class SelectionError(SkillCompilerError):
    """Selector inputs or dependency closure violate the sealed contract."""


class SkillContextOverflowError(SkillCompilerError):
    """Mandatory verbatim content does not fit the sealed semantic budget."""

    def __init__(self, *, status: str, available_tokens: int, required_tokens: int) -> None:
        super().__init__(
            f"{status}: required Skill context {required_tokens} exceeds "
            f"available budget {available_tokens}"
        )
        self.status = status
        self.available_tokens = available_tokens
        self.required_tokens = required_tokens
        self.auto_summarize_to_fit = False
        self.silent_truncation = False


@dataclass(frozen=True)
class SkillSectionV1:
    skill_id: str
    section_id: str
    source_path: str
    source_file_sha256: str
    section_content_sha256: str
    heading_path: tuple[str, ...]
    source_span_or_ast_node: Mapping[str, int]
    section_order: int
    stage_ownership: str
    stage_ownership_exception: str | None
    model_visible_safe: bool
    demand_tags: tuple[str, ...]
    capability_tags: tuple[str, ...]
    dependency_section_ids: tuple[str, ...]
    selection_class: str
    contract_ids: tuple[str, ...]
    source_text: str


@dataclass(frozen=True)
class SelectionInputV1:
    resolved_skill_ids: tuple[str, ...]
    resolved_skill_source_hashes: tuple[tuple[str, str], ...]
    stage: str
    substage: str
    task_contract_id: str
    task_contract_schema_sha256: str
    creative_demand_class: str
    authority_fact_hashes: tuple[tuple[str, str], ...]
    include_optional_support: bool = False


@dataclass(frozen=True)
class BudgetInputV1:
    safe_context_window_tokens: int
    output_reserve_tokens: int
    non_skill_input_tokens: int
    wrapper_and_estimator_margin_tokens: int
    stage_split_available: bool = False

    @property
    def maximum_total_input_tokens(self) -> int:
        return math.floor(self.safe_context_window_tokens * 0.75)

    @property
    def available_skill_tokens(self) -> int:
        return max(
            0,
            self.maximum_total_input_tokens
            - self.output_reserve_tokens
            - self.non_skill_input_tokens
            - self.wrapper_and_estimator_margin_tokens,
        )


@dataclass(frozen=True)
class RenderedSectionPartV1:
    section_id: str
    source_path: str
    body: str
    body_start: int
    body_end: int


@dataclass(frozen=True)
class RenderedSkillContextV1:
    text: str
    sha256: str
    chars: int
    token_estimate: int
    parts: tuple[RenderedSectionPartV1, ...]
    creative_semantic_reauthoring_count: int = 0
    runtime_generated_creative_sentence_count: int = 0
    wrapper_creative_summary_count: int = 0


@dataclass(frozen=True)
class SkillContextReceiptV1:
    compiler_version: str
    stage: str
    substage: str
    task_id_or_case_id: str
    task_contract_id: str
    task_contract_schema_sha256: str
    resolver_version: str
    section_index_version: int
    selector_policy_version: str
    render_policy_version: str
    budget_policy_version: str
    creative_demand_class: str
    selected_skill_ids: tuple[str, ...]
    selected_section_ids: tuple[str, ...]
    source_file_sha256: tuple[tuple[str, str], ...]
    section_content_sha256: tuple[tuple[str, str], ...]
    section_order: tuple[tuple[str, int], ...]
    omitted_section_ids: tuple[str, ...]
    omission_reason: tuple[tuple[str, str], ...]
    rendered_context_sha256: str
    rendered_context_chars: int
    token_estimate: int
    budget: Mapping[str, int | bool]
    capacity_status: str
    overflow_decision: str
    cache_key_sha256: str
    authority_fact_hashes: tuple[tuple[str, str], ...]
    reconstructible: bool = True
    shadow_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "compiler_version": self.compiler_version,
            "stage": self.stage,
            "substage": self.substage,
            "task_id_or_case_id": self.task_id_or_case_id,
            "task_contract_id": self.task_contract_id,
            "task_contract_schema_sha256": self.task_contract_schema_sha256,
            "resolver_version": self.resolver_version,
            "section_index_version": self.section_index_version,
            "selector_policy_version": self.selector_policy_version,
            "render_policy_version": self.render_policy_version,
            "budget_policy_version": self.budget_policy_version,
            "creative_demand_class": self.creative_demand_class,
            "selected_skill_ids": list(self.selected_skill_ids),
            "selected_section_ids": list(self.selected_section_ids),
            "source_file_sha256": dict(self.source_file_sha256),
            "section_content_sha256": dict(self.section_content_sha256),
            "section_order": dict(self.section_order),
            "omitted_section_ids": list(self.omitted_section_ids),
            "omission_reason": dict(self.omission_reason),
            "rendered_context_sha256": self.rendered_context_sha256,
            "rendered_context_chars": self.rendered_context_chars,
            "token_estimate": self.token_estimate,
            "budget": dict(self.budget),
            "capacity_status": self.capacity_status,
            "overflow_decision": self.overflow_decision,
            "cache_key_sha256": self.cache_key_sha256,
            "authority_fact_hashes": dict(self.authority_fact_hashes),
            "reconstructible": self.reconstructible,
            "shadow_only": self.shadow_only,
        }


@dataclass(frozen=True)
class SkillContextMaterializationV1:
    selected: tuple[SkillSectionV1, ...]
    rendered: RenderedSkillContextV1
    receipt: SkillContextReceiptV1


class SkillSectionIndexV1:
    """Validated immutable view over the explicit repo-owned section index."""

    def __init__(
        self, *, repository_root: Path, source_root: str,
        skill_ids: tuple[str, ...], skill_source_sha256: Mapping[str, str],
        sections: tuple[SkillSectionV1, ...],
        known_planning_wrong_layer_ids: frozenset[str],
        planning_shared_subset_exception_ids: frozenset[str],
    ) -> None:
        self.repository_root = repository_root
        self.source_root = source_root
        self.skill_ids = skill_ids
        self.skill_source_sha256 = dict(skill_source_sha256)
        self.sections = sections
        self.known_planning_wrong_layer_ids = known_planning_wrong_layer_ids
        self.planning_shared_subset_exception_ids = (
            planning_shared_subset_exception_ids
        )
        self.by_id = {section.section_id: section for section in sections}

    @classmethod
    def load(cls, index_path: Path, repository_root: Path) -> "SkillSectionIndexV1":
        repository_root = repository_root.resolve()
        try:
            payload = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SectionIndexError("section index is unreadable") from exc
        if payload.get("schema") != INDEX_SCHEMA or payload.get("version") != INDEX_VERSION:
            raise SectionIndexError("unsupported section index schema/version")
        expected_definition_hash = str(payload.get("index_definition_sha256") or "")
        unsigned_index = dict(payload)
        unsigned_index.pop("index_definition_sha256", None)
        if (
            not SHA256_RE.fullmatch(expected_definition_hash)
            or _sha256_bytes(_canonical_json(unsigned_index))
            != expected_definition_hash
        ):
            raise SectionIndexError("section index definition hash mismatch")
        skill_ids = tuple(payload.get("short_used_skill_ids") or ())
        if not skill_ids or len(skill_ids) != len(set(skill_ids)):
            raise SectionIndexError("short-used Skill identity set is empty or duplicated")
        source_root = str(payload.get("source_root") or "")
        skill_hashes = dict(payload.get("skill_source_sha256") or {})
        if set(skill_hashes) != set(skill_ids):
            raise SectionIndexError("Skill source hash coverage is incomplete")
        for value in skill_hashes.values():
            if not SHA256_RE.fullmatch(str(value)):
                raise SectionIndexError("Skill source hash is not SHA-256")

        raw_sections = payload.get("sections")
        if not isinstance(raw_sections, list) or not raw_sections:
            raise SectionIndexError("section index has no sections")
        sections: list[SkillSectionV1] = []
        seen_ids: set[str] = set()
        file_cache: dict[str, tuple[bytes, str, list[str]]] = {}
        for raw in raw_sections:
            section_id = str(raw.get("section_id") or "")
            if not section_id or section_id in seen_ids:
                raise SectionIndexError("section IDs must be present and unique")
            seen_ids.add(section_id)
            skill_id = str(raw.get("skill_id") or "")
            if skill_id not in skill_ids:
                raise SectionIndexError(f"unknown Skill for section {section_id}")
            source_path = str(raw.get("source_path") or "")
            source = (repository_root / source_path).resolve()
            if not source.is_relative_to(repository_root) or not source.is_file():
                raise SectionIndexError(f"source path unavailable for {section_id}")
            if source_path not in file_cache:
                data = source.read_bytes()
                canonical = _canonical_text(data.decode("utf-8"))
                file_cache[source_path] = (
                    data, _sha256_bytes(data), canonical.splitlines(keepends=True),
                )
            _, actual_file_hash, lines = file_cache[source_path]
            expected_file_hash = str(raw.get("source_file_sha256") or "")
            if actual_file_hash != expected_file_hash:
                raise SectionIndexError(
                    f"source file hash mismatch for {source_path}"
                )
            span = raw.get("source_span_or_ast_node") or {}
            start = int(span.get("start_line") or 0)
            end = int(span.get("end_line") or 0)
            if start < 1 or end < start or end > len(lines):
                raise SectionIndexError(f"invalid source span for {section_id}")
            source_text = "".join(lines[start - 1:end]).rstrip() + "\n"
            expected_section_hash = str(raw.get("section_content_sha256") or "")
            if _sha256_text(source_text) != expected_section_hash:
                raise SectionIndexError(
                    f"section content hash mismatch for {section_id}"
                )
            heading_path = tuple(raw.get("heading_path") or ())
            heading_line = source_text.splitlines()[0] if source_text else ""
            heading_match = re.match(r"^#{1,6}\s+(.+?)\s*$", heading_line)
            if not heading_path or not heading_match or heading_match.group(1) != heading_path[-1]:
                raise SectionIndexError(f"heading identity mismatch for {section_id}")
            selection_class = str(raw.get("selection_class") or "")
            if selection_class not in SELECTION_CLASSES:
                raise SectionIndexError(f"unknown selection class for {section_id}")
            demand_tags = tuple(raw.get("demand_tags") or ())
            if any(tag not in DEMAND_CLASSES for tag in demand_tags):
                raise SectionIndexError(f"unknown demand tag for {section_id}")
            sections.append(SkillSectionV1(
                skill_id=skill_id,
                section_id=section_id,
                source_path=source_path,
                source_file_sha256=expected_file_hash,
                section_content_sha256=expected_section_hash,
                heading_path=heading_path,
                source_span_or_ast_node={"start_line": start, "end_line": end},
                section_order=int(raw.get("section_order")),
                stage_ownership=str(raw.get("stage_ownership") or "UNKNOWN"),
                stage_ownership_exception=(
                    str(raw["stage_ownership_exception"])
                    if raw.get("stage_ownership_exception") else None
                ),
                model_visible_safe=raw.get("model_visible_safe") is True,
                demand_tags=demand_tags,
                capability_tags=tuple(raw.get("capability_tags") or ()),
                dependency_section_ids=tuple(raw.get("dependency_section_ids") or ()),
                selection_class=selection_class,
                contract_ids=tuple(raw.get("contract_ids") or ()),
                source_text=source_text,
            ))
        by_id = {section.section_id: section for section in sections}
        for section in sections:
            missing = set(section.dependency_section_ids) - set(by_id)
            if missing:
                raise SectionIndexError(
                    f"missing dependency for {section.section_id}: {sorted(missing)}"
                )
        wrong = frozenset(payload.get("known_planning_wrong_layer_section_ids") or ())
        if not wrong <= set(by_id):
            raise SectionIndexError("known wrong-layer identity is missing from index")
        exceptions = frozenset(
            payload.get("planning_shared_subset_exception_section_ids") or ()
        )
        if not exceptions <= set(by_id):
            raise SectionIndexError("shared-subset exception identity is missing")
        for section_id in exceptions:
            section = by_id[section_id]
            if not section.stage_ownership_exception or not section.model_visible_safe:
                raise SectionIndexError("shared-subset exception is not exact and safe")
        return cls(
            repository_root=repository_root,
            source_root=source_root,
            skill_ids=skill_ids,
            skill_source_sha256=skill_hashes,
            sections=tuple(sections),
            known_planning_wrong_layer_ids=wrong,
            planning_shared_subset_exception_ids=exceptions,
        )


class SelectiveSkillCompilerV1:
    """Compile exact original sections into a bounded shadow-only context."""

    PLANNING_ALLOWED_OWNERSHIP: ClassVar[frozenset[str]] = frozenset({
        "PLANNING_EVENT_REALIZATION", "SHARED_CREATIVE_CORE", "AUTHORITY_ONLY",
    })
    _CLASS_RANK: ClassVar[Mapping[str, int]] = {
        "ALWAYS_ON_STAGE_CORE": 0,
        "CONTRACT_SPECIFIC": 1,
        "DEMAND_SPECIFIC": 2,
        "OPTIONAL_SUPPORT": 3,
        "EXCLUDED_WRONG_LAYER": 4,
    }

    def __init__(self, index: SkillSectionIndexV1) -> None:
        self.index = index

    def _validate_request(self, request: SelectionInputV1) -> None:
        if (request.stage, request.substage) != ("planning", "event_realization"):
            raise SelectionError("selector is scoped to Planning/Event Realization")
        if request.creative_demand_class not in DEMAND_CLASSES:
            raise SelectionError("unknown creative demand class")
        if not request.task_contract_id or not SHA256_RE.fullmatch(
            request.task_contract_schema_sha256
        ):
            raise SelectionError("task contract identity is incomplete")
        if len(request.resolved_skill_ids) != len(set(request.resolved_skill_ids)):
            raise SelectionError("resolved Skill IDs must be unique and ordered")
        if not set(request.resolved_skill_ids) <= set(self.index.skill_ids):
            raise SelectionError("resolved Skill is outside the checked-in index")
        hashes = dict(request.resolved_skill_source_hashes)
        if set(hashes) != set(request.resolved_skill_ids):
            raise SelectionError("resolved Skill source hash coverage is incomplete")
        if any(not SHA256_RE.fullmatch(value) for value in hashes.values()):
            raise SelectionError("resolved Skill source hash is not SHA-256")
        if any(not name or not SHA256_RE.fullmatch(value) for name, value in request.authority_fact_hashes):
            raise SelectionError("authority selection facts must be named hashes")

    def _ownership_allowed(self, section: SkillSectionV1) -> bool:
        return (
            section.model_visible_safe
            and (
                section.stage_ownership in self.PLANNING_ALLOWED_OWNERSHIP
                or section.section_id
                in self.index.planning_shared_subset_exception_ids
            )
        )

    def _sort_key(
        self, section: SkillSectionV1, skill_rank: Mapping[str, int],
    ) -> tuple[int, int, str, int, str]:
        return (
            self._CLASS_RANK[section.selection_class],
            skill_rank[section.skill_id],
            section.source_path,
            section.section_order,
            section.section_id,
        )

    def select(self, request: SelectionInputV1) -> tuple[SkillSectionV1, ...]:
        self._validate_request(request)
        skill_ids = set(request.resolved_skill_ids)
        chosen: dict[str, SkillSectionV1] = {}
        for section in self.index.sections:
            if section.skill_id not in skill_ids:
                continue
            if not self._ownership_allowed(section):
                continue
            include = (
                section.selection_class == "ALWAYS_ON_STAGE_CORE"
                or (
                    section.selection_class == "DEMAND_SPECIFIC"
                    and request.creative_demand_class in section.demand_tags
                )
                or (
                    section.selection_class == "CONTRACT_SPECIFIC"
                    and request.task_contract_id in section.contract_ids
                )
                or (
                    section.selection_class == "OPTIONAL_SUPPORT"
                    and request.include_optional_support
                )
            )
            if include:
                chosen[section.section_id] = section

        visiting: set[str] = set()
        visited: set[str] = set()

        def include_dependencies(section: SkillSectionV1) -> None:
            if section.section_id in visiting:
                raise SelectionError(f"dependency cycle at {section.section_id}")
            if section.section_id in visited:
                return
            visiting.add(section.section_id)
            for dependency_id in section.dependency_section_ids:
                dependency = self.index.by_id.get(dependency_id)
                if dependency is None:
                    raise SelectionError(f"missing dependency {dependency_id}")
                if dependency.skill_id not in skill_ids:
                    raise SelectionError(f"dependency Skill was not resolved: {dependency_id}")
                if not self._ownership_allowed(dependency):
                    raise SelectionError(f"dependency ownership conflict: {dependency_id}")
                if dependency.selection_class == "EXCLUDED_WRONG_LAYER":
                    raise SelectionError(f"dependency is excluded wrong-layer: {dependency_id}")
                chosen[dependency.section_id] = dependency
                include_dependencies(dependency)
            visiting.remove(section.section_id)
            visited.add(section.section_id)

        for section in tuple(chosen.values()):
            include_dependencies(section)
        selected_ids = set(chosen)
        contaminated = (
            selected_ids & self.index.known_planning_wrong_layer_ids
            - self.index.planning_shared_subset_exception_ids
        )
        if contaminated:
            raise SelectionError(
                f"known wrong-layer section selected: {sorted(contaminated)}"
            )
        skill_rank = {skill: rank for rank, skill in enumerate(request.resolved_skill_ids)}
        return tuple(sorted(chosen.values(), key=lambda item: self._sort_key(item, skill_rank)))

    @staticmethod
    def render(selected: Sequence[SkillSectionV1]) -> RenderedSkillContextV1:
        chunks: list[str] = []
        parts: list[RenderedSectionPartV1] = []
        cursor = 0
        for ordinal, section in enumerate(selected):
            if ordinal:
                separator = "\n\n"
                chunks.append(separator)
                cursor += len(separator)
            opening = (
                f'<skill-section id="{section.section_id}" '
                f'source="{section.skill_id}/{Path(section.source_path).name}">\n'
            )
            chunks.append(opening)
            cursor += len(opening)
            body_start = cursor
            chunks.append(section.source_text)
            cursor += len(section.source_text)
            body_end = cursor
            closing = "</skill-section>"
            chunks.append(closing)
            cursor += len(closing)
            parts.append(RenderedSectionPartV1(
                section_id=section.section_id,
                source_path=section.source_path,
                body=section.source_text,
                body_start=body_start,
                body_end=body_end,
            ))
        text = "".join(chunks) + ("\n" if chunks else "")
        return RenderedSkillContextV1(
            text=text,
            sha256=_sha256_text(text),
            chars=len(text),
            token_estimate=estimate_input_tokens(text),
            parts=tuple(parts),
        )

    @staticmethod
    def _cache_key_payload(
        request: SelectionInputV1, selected: Sequence[SkillSectionV1],
        budget: BudgetInputV1,
    ) -> dict[str, Any]:
        return {
            "compiler_version": COMPILER_VERSION,
            "resolver_version": RESOLVER_VERSION,
            "section_index_version": INDEX_VERSION,
            "selector_policy_version": SELECTOR_POLICY_VERSION,
            "render_policy_version": RENDER_POLICY_VERSION,
            "budget_policy_version": BUDGET_POLICY_VERSION,
            "stage": request.stage,
            "substage": request.substage,
            "task_contract_id": request.task_contract_id,
            "task_contract_schema_sha256": request.task_contract_schema_sha256,
            "creative_demand_class": request.creative_demand_class,
            "authority_fact_hashes": list(request.authority_fact_hashes),
            "resolved_skill_ids": list(request.resolved_skill_ids),
            "resolved_skill_source_hashes": list(request.resolved_skill_source_hashes),
            "selected_sections": [
                [section.section_id, section.section_content_sha256]
                for section in selected
            ],
            "capacity_profile": {
                "safe_context_window_tokens": budget.safe_context_window_tokens,
                "output_reserve_tokens": budget.output_reserve_tokens,
                "non_skill_input_tokens": budget.non_skill_input_tokens,
                "wrapper_and_estimator_margin_tokens": (
                    budget.wrapper_and_estimator_margin_tokens
                ),
                "stage_split_available": budget.stage_split_available,
            },
        }

    def materialize(
        self, request: SelectionInputV1, budget: BudgetInputV1, *, task_case: str,
    ) -> SkillContextMaterializationV1:
        selected = list(self.select(request))
        initially_selected = tuple(selected)
        rendered = self.render(selected)
        omitted_reasons: dict[str, str] = {}
        while rendered.token_estimate > budget.available_skill_tokens:
            optional_index = next((
                index for index in range(len(selected) - 1, -1, -1)
                if selected[index].selection_class == "OPTIONAL_SUPPORT"
                and not any(
                    selected[index].section_id in other.dependency_section_ids
                    for other in selected
                    if other.section_id != selected[index].section_id
                )
            ), None)
            if optional_index is None:
                status = (
                    "STAGE_SPLIT_REQUIRED"
                    if budget.stage_split_available else "FAIL_CLOSED"
                )
                raise SkillContextOverflowError(
                    status=status,
                    available_tokens=budget.available_skill_tokens,
                    required_tokens=rendered.token_estimate,
                )
            removed = selected.pop(optional_index)
            omitted_reasons[removed.section_id] = "optional_support_overflow"
            rendered = self.render(selected)

        selected_tuple = tuple(selected)
        initially_selected_ids = {item.section_id for item in initially_selected}
        selected_ids = {item.section_id for item in selected_tuple}
        for section_id in sorted(initially_selected_ids - selected_ids):
            omitted_reasons.setdefault(section_id, "optional_support_overflow")
        cache_key = _sha256_bytes(_canonical_json(
            self._cache_key_payload(request, selected_tuple, budget)
        ))
        receipt = SkillContextReceiptV1(
            compiler_version=COMPILER_VERSION,
            stage=request.stage,
            substage=request.substage,
            task_id_or_case_id=task_case,
            task_contract_id=request.task_contract_id,
            task_contract_schema_sha256=request.task_contract_schema_sha256,
            resolver_version=RESOLVER_VERSION,
            section_index_version=INDEX_VERSION,
            selector_policy_version=SELECTOR_POLICY_VERSION,
            render_policy_version=RENDER_POLICY_VERSION,
            budget_policy_version=BUDGET_POLICY_VERSION,
            creative_demand_class=request.creative_demand_class,
            selected_skill_ids=tuple(dict.fromkeys(
                section.skill_id for section in selected_tuple
            )),
            selected_section_ids=tuple(section.section_id for section in selected_tuple),
            source_file_sha256=tuple((
                section.section_id, section.source_file_sha256,
            ) for section in selected_tuple),
            section_content_sha256=tuple((
                section.section_id, section.section_content_sha256,
            ) for section in selected_tuple),
            section_order=tuple((
                section.section_id, section.section_order,
            ) for section in selected_tuple),
            omitted_section_ids=tuple(sorted(omitted_reasons)),
            omission_reason=tuple(sorted(omitted_reasons.items())),
            rendered_context_sha256=rendered.sha256,
            rendered_context_chars=rendered.chars,
            token_estimate=rendered.token_estimate,
            budget={
                "safe_context_window_tokens": budget.safe_context_window_tokens,
                "maximum_total_input_tokens": budget.maximum_total_input_tokens,
                "output_reserve_tokens": budget.output_reserve_tokens,
                "non_skill_input_tokens": budget.non_skill_input_tokens,
                "wrapper_and_estimator_margin_tokens": (
                    budget.wrapper_and_estimator_margin_tokens
                ),
                "available_skill_tokens": budget.available_skill_tokens,
                "stage_split_available": budget.stage_split_available,
            },
            capacity_status="PASS",
            overflow_decision=(
                "OPTIONAL_SUPPORT_DROPPED" if omitted_reasons else "NONE"
            ),
            cache_key_sha256=cache_key,
            authority_fact_hashes=request.authority_fact_hashes,
        )
        return SkillContextMaterializationV1(
            selected=selected_tuple, rendered=rendered, receipt=receipt,
        )

    def reconstruct(self, receipt: SkillContextReceiptV1) -> str:
        sections: list[SkillSectionV1] = []
        for section_id in receipt.selected_section_ids:
            section = self.index.by_id.get(section_id)
            if section is None:
                raise SectionIndexError(f"receipt section is missing: {section_id}")
            sections.append(section)
        rendered = self.render(sections)
        if rendered.sha256 != receipt.rendered_context_sha256:
            raise SectionIndexError("receipt rendered context hash is stale")
        return rendered.text


def hash_only_shadow_projection(
    materialization: SkillContextMaterializationV1,
) -> dict[str, Any]:
    """Return the bounded observer shape; never persist source or story text."""

    receipt = materialization.receipt
    return {
        "schema": "SelectiveSkillContextShadowProjectionV1",
        "shadow_only": True,
        "selected_skill_ids": list(receipt.selected_skill_ids),
        "selected_section_ids": list(receipt.selected_section_ids),
        "rendered_context_sha256": receipt.rendered_context_sha256,
        "rendered_context_chars": receipt.rendered_context_chars,
        "token_estimate": receipt.token_estimate,
        "capacity_status": receipt.capacity_status,
        "overflow_decision": receipt.overflow_decision,
        "cache_key_sha256": receipt.cache_key_sha256,
        "model_input_used": False,
        "validator_used": False,
        "authority_used": False,
        "router_used": False,
        "retry_used": False,
    }


class SelectiveSkillShadowObserverV1:
    """Callable adapter for the WorkflowService shadow observer seam.

    The workflow passes hashes, counts, identities, and local capacity facts
    only.  The observer never receives the production prompt or story text.
    """

    def __init__(
        self, compiler: SelectiveSkillCompilerV1,
        sink: Any | None = None,
    ) -> None:
        self.compiler = compiler
        self.sink = sink
        self.observations: list[dict[str, Any]] = []

    def __call__(self, payload: Mapping[str, object]) -> dict[str, Any]:
        demand = payload.get("creative_demand_class")
        if not isinstance(demand, str) or demand not in DEMAND_CLASSES:
            raise SelectionError("unknown creative demand class")
        skill_ids = tuple(str(value) for value in payload["resolved_skill_ids"])
        skill_hashes = tuple(
            (str(name), str(value))
            for name, value in payload["resolved_skill_source_hashes"]
        )
        authority_hashes = tuple(
            (str(name), str(value))
            for name, value in payload["authority_fact_hashes"]
        )
        request = SelectionInputV1(
            resolved_skill_ids=skill_ids,
            resolved_skill_source_hashes=skill_hashes,
            stage=str(payload["stage"]),
            substage=str(payload["substage"]),
            task_contract_id=str(payload["task_contract_id"]),
            task_contract_schema_sha256=str(
                payload["task_contract_schema_sha256"]
            ),
            creative_demand_class=demand,
            authority_fact_hashes=authority_hashes,
        )
        budget = BudgetInputV1(
            safe_context_window_tokens=int(payload["safe_context_window_tokens"]),
            output_reserve_tokens=int(payload["output_reserve_tokens"]),
            non_skill_input_tokens=int(payload["non_skill_input_tokens"]),
            wrapper_and_estimator_margin_tokens=int(
                payload["wrapper_and_estimator_margin_tokens"]
            ),
            stage_split_available=bool(payload.get("stage_split_available", False)),
        )
        materialized = self.compiler.materialize(
            request, budget, task_case=str(payload["task_case"]),
        )
        projection = hash_only_shadow_projection(materialized)
        self.observations.append(projection)
        if self.sink is not None:
            self.sink(projection)
        return projection


def exact_body_hashes(sections: Iterable[SkillSectionV1]) -> dict[str, str]:
    """Small test/diagnostic helper for verbatim-fidelity receipts."""

    return {
        section.section_id: _sha256_text(section.source_text)
        for section in sections
    }
