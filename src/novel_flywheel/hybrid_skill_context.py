"""Default-disabled Hybrid Skill context compiler for offline shadow use.

The compiler preserves the production baseline as an exact byte prefix and
adds only hash-bound, original-verbatim Skill sections selected by a checked-in
semantic packet index.  It never calls a Provider, mutates narrative authority,
or returns bytes to the production model-input path.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, ClassVar, Mapping, Sequence

from novel_flywheel.context_policy import estimate_input_tokens
from novel_flywheel.selective_skill_compiler import (
    SkillSectionIndexV1,
    SkillSectionV1,
    SelectiveSkillCompilerV1,
)


HYBRID_CONTEXT_VERSION = "hybrid-skill-context-shadow-v1"
HYBRID_INDEX_SCHEMA = "HybridSkillSectionIndexV2"
HYBRID_INDEX_VERSION = 2
HYBRID_ARCHITECTURE_DECISION = (
    "COMPOSED_HYBRID_CROSS_SKILL_SCENE_PACKET_WITH_"
    "VERBATIM_NEIGHBORHOOD_CLOSURE"
)
DEFAULT_HYBRID_SKILL_CONTEXT_SHADOW_ENABLED = False
SUPPLEMENT_SEPARATOR = (
    "\n\n--- HYBRID VERBATIM SKILL SUPPLEMENT "
    "(advisory; authority unchanged) ---\n\n"
)
WRAPPER_VERSION = "hybrid-verbatim-supplement-wrapper-v1"
DELIMITER_VERSION = "hybrid-supplement-delimiter-v1"

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DEMAND_CLASSES = frozenset({
    "character-heavy",
    "world-heavy",
    "conflict-pacing-heavy",
    "setup-payoff-heavy",
    "mixed",
})
DEMAND_FEATURES = frozenset({
    "character_agency_motivation",
    "relationship_consequence",
    "causal_coherence",
    "subtext_dramatization",
    "scene_pressure",
    "specificity",
    "setup_payoff",
    "voice_readiness",
    "anti_template_realization",
})
ACTIONABILITY_CLASSES = frozenset({
    "HIGH_ACTIONABILITY", "MEDIUM_ACTIONABILITY", "LOW_ACTIONABILITY",
})
DEPENDENCY_TYPES = frozenset({
    "FORMAL_DEPENDENCY",
    "PARENT_CONTEXT_DEPENDENCY",
    "QUALIFIER_DEPENDENCY",
    "ANTI_PATTERN_DEPENDENCY",
    "EXAMPLE_DEPENDENCY",
    "APPLICATION_BRIDGE_DEPENDENCY",
    "SCENE_REALIZATION_DEPENDENCY",
    "CROSS_SKILL_SEMANTIC_DEPENDENCY",
})
OVERLAP_CLASSES = frozenset({
    "BENEFICIAL_REINFORCEMENT",
    "REDUNDANT_DUPLICATION",
    "CONTRADICTORY_RESTATEMENT",
    "DETAIL_ENRICHMENT",
    "QUALIFIER_RESTORATION",
    "ANTI_PATTERN_RESTORATION",
})
ALLOWED_SUPPLEMENT_OWNERSHIP = frozenset({
    "PLANNING_EVENT_REALIZATION", "SHARED_CREATIVE_CORE",
})


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha_text(value: str) -> str:
    return _sha_bytes(value.encode("utf-8"))


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _canonical_hash(value: object) -> str:
    return _sha_bytes(_canonical_json_bytes(value))


def _require_sha(value: str, label: str) -> None:
    if not SHA256_RE.fullmatch(value):
        raise HybridIndexError(
            "MALFORMED_HASH_IDENTITY", label,
        )


class HybridSkillContextError(ValueError):
    """Typed, redaction-safe Hybrid compilation failure."""

    def __init__(self, code: str, invariant: str) -> None:
        super().__init__(code)
        self.code = code
        self.invariant = invariant


class HybridIndexError(HybridSkillContextError):
    pass


class HybridDemandError(HybridSkillContextError):
    pass


class HybridDependencyError(HybridSkillContextError):
    pass


class HybridOwnershipError(HybridSkillContextError):
    pass


class HybridVerbatimError(HybridSkillContextError):
    pass


class HybridBaselineIdentityError(HybridSkillContextError):
    pass


class HybridReferenceIdentityError(HybridSkillContextError):
    pass


class HybridCapacityError(HybridSkillContextError):
    def __init__(self, *, required_tokens: int, available_tokens: int) -> None:
        super().__init__(
            "HYBRID_SUPPLEMENT_CAPACITY_NO_GO",
            "complete typed dependency closure must fit without truncation",
        )
        self.required_tokens = required_tokens
        self.available_tokens = available_tokens


class HybridContradictionError(HybridSkillContextError):
    pass


@dataclass(frozen=True)
class HybridSectionPolicyV2:
    section_id: str
    actionability_class: str
    actionability_reason: str
    target_semantic_functions: tuple[str, ...]
    overlap_classification: str
    stage_ownership_exception: str | None = None
    cycle_group_id: str | None = None


@dataclass(frozen=True)
class HybridDependencyEdgeV1:
    from_section_id: str
    to_section_id: str
    dependency_type: str
    source_of_truth: str
    reason: str
    cycle_allowed: bool = False


@dataclass(frozen=True)
class HybridSemanticPacketV1:
    packet_id: str
    root_section_ids: tuple[str, ...]
    semantic_functions: tuple[str, ...]
    priority: int


@dataclass(frozen=True)
class HybridDemandFeaturesV1:
    creative_demand_class: str
    active_features: tuple[str, ...]
    active_signal_keys: tuple[str, ...]
    demand_features_sha256: str


@dataclass(frozen=True)
class HybridProtectedBudgetV1:
    safe_context_window_tokens: int
    output_reserve_tokens: int
    mandatory_authority_tokens: int
    reference_guidance_tokens: int
    baseline_skill_foundation_tokens: int
    output_contract_tokens: int
    wrapper_and_estimator_margin_tokens: int

    @property
    def maximum_total_input_tokens(self) -> int:
        return math.floor(self.safe_context_window_tokens * 0.75)

    @property
    def protected_without_supplement_tokens(self) -> int:
        return (
            self.output_reserve_tokens
            + self.mandatory_authority_tokens
            + self.reference_guidance_tokens
            + self.baseline_skill_foundation_tokens
            + self.output_contract_tokens
            + self.wrapper_and_estimator_margin_tokens
        )

    @property
    def available_supplement_tokens(self) -> int:
        return max(
            0,
            self.maximum_total_input_tokens
            - self.protected_without_supplement_tokens,
        )

    def receipt(self, supplement_tokens: int) -> dict[str, int | str]:
        return {
            "MANDATORY_AUTHORITY_BUDGET": self.mandatory_authority_tokens,
            "REFERENCE_DERIVED_GUIDANCE_BUDGET": self.reference_guidance_tokens,
            "BASELINE_SKILL_FOUNDATION_BUDGET": (
                self.baseline_skill_foundation_tokens
            ),
            "VERBATIM_SUPPLEMENT_BUDGET": supplement_tokens,
            "OUTPUT_CONTRACT_BUDGET": self.output_contract_tokens,
            "OUTPUT_RESERVE_TOKENS": self.output_reserve_tokens,
            "WRAPPER_AND_ESTIMATOR_MARGIN_TOKENS": (
                self.wrapper_and_estimator_margin_tokens
            ),
            "MAXIMUM_TOTAL_INPUT_TOKENS": self.maximum_total_input_tokens,
            "AVAILABLE_SUPPLEMENT_TOKENS": self.available_supplement_tokens,
            "BASELINE_TRUNCATED_FOR_SUPPLEMENT": "NO",
            "REFERENCE_GUIDANCE_TRUNCATED_FOR_SUPPLEMENT": "NO",
            "BASELINE_SHED_FOR_SUPPLEMENT": "NO",
            "REFERENCE_GUIDANCE_SHED_FOR_SUPPLEMENT": "NO",
            "HYBRID_DYNAMIC_SILENT_SHEDDING": "NO",
        }


@dataclass(frozen=True)
class HybridShadowInputV1:
    stage: str
    substage: str
    task_case: str
    task_contract_id: str
    task_contract_schema_sha256: str
    creative_demand_class: str
    demand_signals: Mapping[str, object]
    resolved_skill_ids: tuple[str, ...]
    resolved_skill_source_hashes: tuple[tuple[str, str], ...]
    authority_fact_hashes: tuple[tuple[str, str], ...]
    production_baseline_context: str
    baseline_source_receipt: Mapping[str, object]
    baseline_compactor_receipt: Mapping[str, object]
    protected_non_skill_prefix: str
    reference_guidance_context: str
    production_model_input_sha256: str
    budget: HybridProtectedBudgetV1
    expected_baseline_context_sha256: str | None = None
    expected_reference_guidance_sha256: str | None = None


@dataclass(frozen=True)
class HybridSkillContextMaterializationV1:
    baseline_context: str
    supplement_text: str
    final_hybrid_advisory: str
    ordered_sections: tuple[SkillSectionV1, ...]
    receipt: Mapping[str, object]


class HybridSkillSectionIndexV2:
    """Validated data-only semantic packet overlay on source index V1."""

    def __init__(
        self,
        *,
        source_index: SkillSectionIndexV1,
        definition_sha256: str,
        design_manifest_definition_sha256: str,
        root_cause_manifest_definition_sha256: str,
        section_policies: Mapping[str, HybridSectionPolicyV2],
        packets: Mapping[str, HybridSemanticPacketV1],
        dependency_edges: tuple[HybridDependencyEdgeV1, ...],
        demand_class_features: Mapping[str, tuple[str, ...]],
        demand_packet_order: Mapping[str, tuple[str, ...]],
        signal_feature_map: Mapping[str, tuple[str, ...]],
    ) -> None:
        self.source_index = source_index
        self.definition_sha256 = definition_sha256
        self.design_manifest_definition_sha256 = (
            design_manifest_definition_sha256
        )
        self.root_cause_manifest_definition_sha256 = (
            root_cause_manifest_definition_sha256
        )
        self.section_policies = dict(section_policies)
        self.packets = dict(packets)
        self.dependency_edges = dependency_edges
        self.demand_class_features = dict(demand_class_features)
        self.demand_packet_order = dict(demand_packet_order)
        self.signal_feature_map = dict(signal_feature_map)

    @classmethod
    def load(
        cls,
        index_v2_path: Path,
        source_index_v1_path: Path,
        repository_root: Path,
    ) -> "HybridSkillSectionIndexV2":
        source_index = SkillSectionIndexV1.load(
            source_index_v1_path, repository_root,
        )
        try:
            payload = json.loads(index_v2_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HybridIndexError(
                "HYBRID_INDEX_UNREADABLE", "Hybrid index must be canonical JSON",
            ) from exc
        if (
            payload.get("schema") != HYBRID_INDEX_SCHEMA
            or payload.get("version") != HYBRID_INDEX_VERSION
        ):
            raise HybridIndexError(
                "HYBRID_INDEX_SCHEMA_MISMATCH", "Hybrid index schema/version",
            )
        expected_hash = str(payload.get("index_definition_sha256") or "")
        unsigned = dict(payload)
        unsigned.pop("index_definition_sha256", None)
        if not SHA256_RE.fullmatch(expected_hash) or _canonical_hash(unsigned) != expected_hash:
            raise HybridIndexError(
                "HYBRID_INDEX_DEFINITION_HASH_MISMATCH",
                "Hybrid index definition must be content addressed",
            )
        architecture = payload.get("architecture_binding") or {}
        if (
            architecture.get("decision") != HYBRID_ARCHITECTURE_DECISION
            or architecture.get("baseline_foundation_protected") != "YES"
            or architecture.get("supplement_replaces_baseline") != "NO"
            or architecture.get("selective_replacement_path_retired") != "YES"
        ):
            raise HybridIndexError(
                "HYBRID_ARCHITECTURE_BINDING_MISMATCH",
                "sealed Hybrid architecture decision",
            )
        source_binding = payload.get("source_index_v1_binding") or {}
        # SkillSectionIndexV1 predates an exposed definition property.  Bind
        # directly to the checked-in content-addressed payload.
        source_payload = json.loads(
            source_index_v1_path.read_text(encoding="utf-8")
        )
        if source_binding.get("index_definition_sha256") != source_payload.get(
            "index_definition_sha256"
        ):
            raise HybridIndexError(
                "SOURCE_INDEX_V1_BINDING_MISMATCH",
                "source section index definition",
            )
        evidence = payload.get("evidence_binding") or {}
        design_sha = str(evidence.get("design_manifest_definition_sha256") or "")
        root_sha = str(
            evidence.get("root_cause_manifest_definition_sha256") or ""
        )
        _require_sha(design_sha, "design manifest definition")
        _require_sha(root_sha, "root-cause manifest definition")

        raw_policies = payload.get("section_policies") or {}
        if not isinstance(raw_policies, dict) or not raw_policies:
            raise HybridIndexError(
                "SECTION_POLICY_MISSING", "section policy coverage",
            )
        section_policies: dict[str, HybridSectionPolicyV2] = {}
        for section_id, row in raw_policies.items():
            if section_id not in source_index.by_id:
                raise HybridIndexError(
                    "MALFORMED_SKILL_SECTION_IDENTITY",
                    "section policy source identity",
                )
            actionability = str(row.get("actionability_class") or "")
            semantic_functions = tuple(row.get("target_semantic_functions") or ())
            overlap = str(row.get("overlap_classification") or "")
            if (
                actionability not in ACTIONABILITY_CLASSES
                or not semantic_functions
                or any(item not in DEMAND_FEATURES for item in semantic_functions)
                or overlap not in OVERLAP_CLASSES
            ):
                raise HybridIndexError(
                    "SECTION_POLICY_INVALID", "typed section policy",
                )
            section_policies[section_id] = HybridSectionPolicyV2(
                section_id=section_id,
                actionability_class=actionability,
                actionability_reason=str(row.get("actionability_reason") or ""),
                target_semantic_functions=semantic_functions,
                overlap_classification=overlap,
                stage_ownership_exception=(
                    str(row["stage_ownership_exception"])
                    if row.get("stage_ownership_exception") else None
                ),
                cycle_group_id=(
                    str(row["cycle_group_id"])
                    if row.get("cycle_group_id") else None
                ),
            )
        raw_packets = payload.get("packet_definitions") or {}
        packets: dict[str, HybridSemanticPacketV1] = {}
        for packet_id, row in raw_packets.items():
            roots = tuple(row.get("root_section_ids") or ())
            functions = tuple(row.get("semantic_functions") or ())
            if (
                not roots
                or any(section_id not in section_policies for section_id in roots)
                or not functions
                or any(item not in DEMAND_FEATURES for item in functions)
            ):
                raise HybridIndexError(
                    "PACKET_DEFINITION_INVALID", "semantic packet identity",
                )
            if any(
                section_policies[item].actionability_class == "LOW_ACTIONABILITY"
                for item in roots
            ):
                raise HybridIndexError(
                    "LOW_ACTIONABILITY_PACKET_SEED",
                    "low-actionability sections are dependency-only",
                )
            packets[packet_id] = HybridSemanticPacketV1(
                packet_id=packet_id,
                root_section_ids=roots,
                semantic_functions=functions,
                priority=int(row.get("priority", 100)),
            )
        edges: list[HybridDependencyEdgeV1] = []
        for row in payload.get("dependency_edges") or ():
            edge = HybridDependencyEdgeV1(
                from_section_id=str(row.get("from_section_id") or ""),
                to_section_id=str(row.get("to_section_id") or ""),
                dependency_type=str(row.get("dependency_type") or ""),
                source_of_truth=str(row.get("source_of_truth") or ""),
                reason=str(row.get("reason") or ""),
                cycle_allowed=row.get("cycle_allowed") is True,
            )
            if (
                edge.from_section_id not in section_policies
                or edge.to_section_id not in section_policies
                or edge.dependency_type not in DEPENDENCY_TYPES
                or not edge.source_of_truth
                or not edge.reason
            ):
                raise HybridIndexError(
                    "DEPENDENCY_EDGE_INVALID", "typed dependency edge",
                )
            edges.append(edge)

        demand_class_features = {
            key: tuple(value)
            for key, value in (payload.get("demand_class_features") or {}).items()
        }
        demand_packet_order = {
            key: tuple(value)
            for key, value in (payload.get("demand_packet_order") or {}).items()
        }
        if set(demand_class_features) != DEMAND_CLASSES or set(
            demand_packet_order
        ) != DEMAND_CLASSES:
            raise HybridIndexError(
                "DEMAND_COVERAGE_INCOMPLETE", "five demand classes",
            )
        if any(
            item not in DEMAND_FEATURES
            for values in demand_class_features.values() for item in values
        ) or any(
            packet_id not in packets
            for values in demand_packet_order.values() for packet_id in values
        ):
            raise HybridIndexError(
                "DEMAND_BINDING_INVALID", "demand feature/packet mapping",
            )
        signal_feature_map = {
            key: tuple(value)
            for key, value in (payload.get("signal_feature_map") or {}).items()
        }
        if any(
            feature not in DEMAND_FEATURES
            for values in signal_feature_map.values() for feature in values
        ):
            raise HybridIndexError(
                "SIGNAL_FEATURE_BINDING_INVALID", "demand signal mapping",
            )
        return cls(
            source_index=source_index,
            definition_sha256=expected_hash,
            design_manifest_definition_sha256=design_sha,
            root_cause_manifest_definition_sha256=root_sha,
            section_policies=section_policies,
            packets=packets,
            dependency_edges=tuple(edges),
            demand_class_features=demand_class_features,
            demand_packet_order=demand_packet_order,
            signal_feature_map=signal_feature_map,
        )


def extract_demand_features_v1(
    demand_class: str,
    signals: Mapping[str, object],
    index: HybridSkillSectionIndexV2,
) -> HybridDemandFeaturesV1:
    """Extract stable, local demand functions without story-text inspection."""

    if demand_class not in DEMAND_CLASSES:
        raise HybridDemandError(
            "UNKNOWN_DEMAND_CLASS", "demand class must be sealed and general",
        )
    unknown_keys = set(signals) - set(index.signal_feature_map)
    if unknown_keys:
        raise HybridDemandError(
            "UNKNOWN_DEMAND_SIGNAL", "unknown signals cannot authorize sections",
        )
    active = set(index.demand_class_features[demand_class])
    active_keys: list[str] = []
    for key in sorted(signals):
        value = signals[key]
        is_active = value is True or (
            isinstance(value, int) and not isinstance(value, bool) and value > 0
        ) or (
            isinstance(value, str)
            and value.casefold() in {"present", "required", "yes", "true", "active"}
        )
        if is_active:
            active_keys.append(key)
            active.update(index.signal_feature_map[key])
    ordered = tuple(sorted(active))
    payload = {
        "creative_demand_class": demand_class,
        "active_features": list(ordered),
        "active_signal_keys": active_keys,
        "extractor_version": "deterministic-demand-feature-extractor-v1",
    }
    return HybridDemandFeaturesV1(
        creative_demand_class=demand_class,
        active_features=ordered,
        active_signal_keys=tuple(active_keys),
        demand_features_sha256=_canonical_hash(payload),
    )


class HybridSkillContextCompilerV1:
    """Compile protected baseline plus complete verbatim semantic packets."""

    _ACTIONABILITY_RANK: ClassVar[Mapping[str, int]] = {
        "HIGH_ACTIONABILITY": 0,
        "MEDIUM_ACTIONABILITY": 1,
        "LOW_ACTIONABILITY": 2,
    }

    def __init__(self, index: HybridSkillSectionIndexV2) -> None:
        self.index = index

    def _validate_input(self, request: HybridShadowInputV1) -> None:
        if (request.stage, request.substage) != ("planning", "event_realization"):
            raise HybridDemandError(
                "WRONG_STAGE", "Hybrid shadow is Planning/Event Realization only",
            )
        _require_sha(request.task_contract_schema_sha256, "task contract schema")
        _require_sha(request.production_model_input_sha256, "production model input")
        hashes = dict(request.resolved_skill_source_hashes)
        if set(hashes) != set(request.resolved_skill_ids):
            raise HybridIndexError(
                "RESOLVED_SKILL_HASH_COVERAGE_INCOMPLETE",
                "resolved Skill source hash coverage",
            )
        for skill_id, expected in self.index.source_index.skill_source_sha256.items():
            if skill_id in hashes and hashes[skill_id] != expected:
                raise HybridIndexError(
                    "RESOLVED_SKILL_SOURCE_HASH_MISMATCH",
                    "resolved Skill source exact identity",
                )
        for name, value in request.authority_fact_hashes:
            if not name:
                raise HybridIndexError(
                    "AUTHORITY_HASH_NAME_MISSING", "authority hash identity",
                )
            _require_sha(value, "authority fact")
        baseline_sha = _sha_text(request.production_baseline_context)
        if (
            request.expected_baseline_context_sha256 is not None
            and request.expected_baseline_context_sha256 != baseline_sha
        ):
            raise HybridBaselineIdentityError(
                "BASELINE_IDENTITY_MISMATCH",
                "production baseline exact byte identity",
            )
        reference_sha = _sha_text(request.reference_guidance_context)
        if (
            request.expected_reference_guidance_sha256 is not None
            and request.expected_reference_guidance_sha256 != reference_sha
        ):
            raise HybridReferenceIdentityError(
                "REFERENCE_GUIDANCE_IDENTITY_MISMATCH",
                "reference guidance exact byte identity",
            )

    def _packet_ids(
        self, features: HybridDemandFeaturesV1,
    ) -> tuple[str, ...]:
        declared_order = self.index.demand_packet_order[
            features.creative_demand_class
        ]
        required = {
            packet_id
            for packet_id, packet in self.index.packets.items()
            if set(packet.semantic_functions) & set(features.active_features)
        }
        required.update(declared_order)
        return tuple(sorted(
            required,
            key=lambda item: (
                declared_order.index(item) if item in declared_order else 10_000,
                self.index.packets[item].priority,
                item,
            ),
        ))

    def _ownership_allowed(self, section: SkillSectionV1) -> bool:
        policy = self.index.section_policies[section.section_id]
        if section.stage_ownership in ALLOWED_SUPPLEMENT_OWNERSHIP:
            return True
        return (
            policy.stage_ownership_exception
            == "PLANNING_CREATIVE_SUPPLEMENT_EXACT_SUBRANGE_V1"
            and section.model_visible_safe
        )

    def _close_dependencies(
        self, root_ids: Sequence[str], resolved_skill_ids: Sequence[str],
    ) -> tuple[
        tuple[SkillSectionV1, ...], tuple[HybridDependencyEdgeV1, ...], tuple[str, ...]
    ]:
        resolved = set(resolved_skill_ids)
        edges_by_from: dict[str, list[HybridDependencyEdgeV1]] = {}
        for edge in self.index.dependency_edges:
            edges_by_from.setdefault(edge.from_section_id, []).append(edge)
        included = set(root_ids)
        frontier = list(root_ids)
        used_edges: list[HybridDependencyEdgeV1] = []
        while frontier:
            current = frontier.pop(0)
            if current not in self.index.source_index.by_id:
                raise HybridDependencyError(
                    "MISSING_DEPENDENCY_TARGET", "dependency target exists",
                )
            for edge in sorted(
                edges_by_from.get(current, ()),
                key=lambda item: (
                    item.dependency_type, item.to_section_id, item.reason,
                ),
            ):
                target = self.index.source_index.by_id.get(edge.to_section_id)
                if target is None or edge.to_section_id not in self.index.section_policies:
                    raise HybridDependencyError(
                        "MISSING_DEPENDENCY_TARGET", "dependency target exists",
                    )
                used_edges.append(edge)
                if edge.to_section_id not in included:
                    included.add(edge.to_section_id)
                    frontier.append(edge.to_section_id)

        sections = {
            section_id: self.index.source_index.by_id[section_id]
            for section_id in included
        }
        for section_id, section in sections.items():
            if section.skill_id not in resolved:
                raise HybridDependencyError(
                    "DEPENDENCY_SKILL_NOT_RESOLVED",
                    "dependency closure stays within resolved Skills",
                )
            if not self._ownership_allowed(section):
                raise HybridOwnershipError(
                    "OWNERSHIP_VIOLATION",
                    f"supplement ownership for {section_id}",
                )
            if section.stage_ownership == "AUTHORITY_ONLY":
                raise HybridOwnershipError(
                    "AUTHORITY_CONTENT_IN_SUPPLEMENT",
                    "supplement cannot contain narrative authority",
                )

        dependency_map: dict[str, set[str]] = {key: set() for key in included}
        edge_map: dict[tuple[str, str], HybridDependencyEdgeV1] = {}
        for edge in used_edges:
            if edge.from_section_id in included and edge.to_section_id in included:
                dependency_map[edge.from_section_id].add(edge.to_section_id)
                edge_map[(edge.from_section_id, edge.to_section_id)] = edge

        ordered: list[str] = []
        temporary: list[str] = []
        permanent: set[str] = set()
        cycle_groups: list[str] = []
        source_rank = {
            skill: rank for rank, skill in enumerate(resolved_skill_ids)
        }

        def sort_key(section_id: str) -> tuple[int, str, int, str]:
            section = sections[section_id]
            return (
                source_rank[section.skill_id],
                section.source_path,
                section.section_order,
                section.section_id,
            )

        def visit(section_id: str) -> None:
            if section_id in permanent:
                return
            if section_id in temporary:
                start = temporary.index(section_id)
                cycle = temporary[start:] + [section_id]
                unique_cycle = tuple(dict.fromkeys(cycle))
                policies = [self.index.section_policies[item] for item in unique_cycle]
                group_ids = {item.cycle_group_id for item in policies}
                owners = {sections[item].stage_ownership for item in unique_cycle}
                cycle_edges = [
                    edge_map[(left, right)]
                    for left, right in zip(cycle, cycle[1:])
                    if (left, right) in edge_map
                ]
                if (
                    len(group_ids) != 1
                    or None in group_ids
                    or len(owners) != 1
                    or not cycle_edges
                    or not all(edge.cycle_allowed for edge in cycle_edges)
                ):
                    raise HybridDependencyError(
                        "DEPENDENCY_CYCLE",
                        "only explicitly declared same-owner SCCs are allowed",
                    )
                cycle_groups.append(str(next(iter(group_ids))))
                return
            temporary.append(section_id)
            for dependency_id in sorted(dependency_map[section_id], key=sort_key):
                visit(dependency_id)
            temporary.pop()
            permanent.add(section_id)
            ordered.append(section_id)

        for section_id in sorted(included, key=sort_key):
            visit(section_id)
        ordered_ids = tuple(dict.fromkeys(ordered))
        return (
            tuple(sections[item] for item in ordered_ids),
            tuple(sorted(
                used_edges,
                key=lambda item: (
                    ordered_ids.index(item.to_section_id),
                    ordered_ids.index(item.from_section_id),
                    item.dependency_type,
                ),
            )),
            tuple(sorted(set(cycle_groups))),
        )

    def materialize(
        self, request: HybridShadowInputV1,
    ) -> HybridSkillContextMaterializationV1:
        self._validate_input(request)
        features = extract_demand_features_v1(
            request.creative_demand_class, request.demand_signals, self.index,
        )
        packet_ids = self._packet_ids(features)
        root_ids = tuple(dict.fromkeys(
            section_id
            for packet_id in packet_ids
            for section_id in self.index.packets[packet_id].root_section_ids
        ))
        sections, used_edges, cycle_groups = self._close_dependencies(
            root_ids, request.resolved_skill_ids,
        )
        policies = [self.index.section_policies[item.section_id] for item in sections]
        distribution = {
            label: sum(item.actionability_class == label for item in policies)
            for label in sorted(ACTIONABILITY_CLASSES)
        }
        if distribution["LOW_ACTIONABILITY"] > (
            distribution["HIGH_ACTIONABILITY"]
            + distribution["MEDIUM_ACTIONABILITY"]
        ):
            raise HybridDemandError(
                "LOW_ACTIONABILITY_LEAF_DOMINANCE",
                "low-actionability dependency leaves cannot dominate",
            )
        contradictions = [
            item.section_id for item in policies
            if item.overlap_classification == "CONTRADICTORY_RESTATEMENT"
        ]
        if contradictions:
            raise HybridContradictionError(
                "UNRESOLVED_CONTRADICTION",
                "supplement cannot contradict protected baseline",
            )

        rendered = SelectiveSkillCompilerV1.render(sections)
        mismatch = sum(
            _sha_text(section.source_text) != section.section_content_sha256
            for section in sections
        )
        if mismatch:
            raise HybridVerbatimError(
                "VERBATIM_MISMATCH", "original source section bytes",
            )
        supplement_tokens = estimate_input_tokens(
            SUPPLEMENT_SEPARATOR + rendered.text
        )
        if supplement_tokens > request.budget.available_supplement_tokens:
            raise HybridCapacityError(
                required_tokens=supplement_tokens,
                available_tokens=request.budget.available_supplement_tokens,
            )
        baseline_sha = _sha_text(request.production_baseline_context)
        reference_sha = _sha_text(request.reference_guidance_context)
        final_advisory = (
            request.protected_non_skill_prefix
            + request.production_baseline_context
            + SUPPLEMENT_SEPARATOR
            + rendered.text
        )
        final_sha = _sha_text(final_advisory)
        closure_rows = [
            {
                "FROM_SECTION_ID": edge.from_section_id,
                "TO_SECTION_ID": edge.to_section_id,
                "DEPENDENCY_TYPE": edge.dependency_type,
                "SOURCE_OF_TRUTH": edge.source_of_truth,
                "REASON": edge.reason,
            }
            for edge in used_edges
        ]
        selector_trace = {
            "DEMAND_FEATURES_SHA": features.demand_features_sha256,
            "PACKET_IDS": list(packet_ids),
            "ROOT_SECTION_IDS": list(root_ids),
            "ORDERED_SECTION_IDS": [item.section_id for item in sections],
            "NO_PAIR_SPECIFIC_RULES": "YES",
            "NO_ANONYMOUS_SAMPLE_SPECIFIC_RULES": "YES",
            "NO_BLIND_PROSE_MEMORIZATION": "YES",
            "NO_RUBRIC_HACKS": "YES",
        }
        packet_receipts = []
        for packet_id in packet_ids:
            packet = self.index.packets[packet_id]
            packet_sections = [
                item for item in sections if item.section_id in packet.root_section_ids
            ]
            packet_render = SelectiveSkillCompilerV1.render(packet_sections)
            packet_receipts.append({
                "PACKET_ID": packet_id,
                "DEMAND_FEATURES_SHA": features.demand_features_sha256,
                "ROOT_SECTION_IDS": list(packet.root_section_ids),
                "DEPENDENCY_SECTION_IDS": [
                    item.section_id for item in sections
                    if item.section_id not in root_ids
                ],
                "SOURCE_SKILLS": list(dict.fromkeys(
                    item.skill_id for item in packet_sections
                )),
                "ORDERED_SECTION_IDS": [item.section_id for item in packet_sections],
                "ORDERED_SECTION_SHAS": [
                    item.section_content_sha256 for item in packet_sections
                ],
                "SEMANTIC_FUNCTIONS": list(packet.semantic_functions),
                "ACTIONABILITY_DISTRIBUTION": {
                    label: sum(
                        self.index.section_policies[item.section_id]
                        .actionability_class == label
                        for item in packet_sections
                    ) for label in sorted(ACTIONABILITY_CLASSES)
                },
                "PACKET_RENDER_SHA": packet_render.sha256,
                "PACKET_CHAR_COUNT": packet_render.chars,
                "PACKET_TOKEN_ESTIMATE": packet_render.token_estimate,
            })
        receipt: dict[str, object] = {
            "schema": "HybridSkillContextReceiptV1",
            "HYBRID_CONTEXT_VERSION": HYBRID_CONTEXT_VERSION,
            "ARCHITECTURE_DECISION": HYBRID_ARCHITECTURE_DECISION,
            "INDEX_DEFINITION_SHA256": self.index.definition_sha256,
            "DESIGN_MANIFEST_DEFINITION_SHA256": (
                self.index.design_manifest_definition_sha256
            ),
            "ROOT_CAUSE_MANIFEST_DEFINITION_SHA256": (
                self.index.root_cause_manifest_definition_sha256
            ),
            "BASELINE_CONTEXT_SHA": baseline_sha,
            "BASELINE_CONTEXT_CHAR_COUNT": len(request.production_baseline_context),
            "BASELINE_CONTEXT_TOKEN_ESTIMATE": estimate_input_tokens(
                request.production_baseline_context
            ),
            "BASELINE_SOURCE_RECEIPT_SHA": _canonical_hash(
                dict(request.baseline_source_receipt)
            ),
            "BASELINE_COMPACTOR_RECEIPT_SHA": _canonical_hash(
                dict(request.baseline_compactor_receipt)
            ),
            "REFERENCE_GUIDANCE_SHA": reference_sha,
            "DEMAND_FEATURES": {
                "creative_demand_class": features.creative_demand_class,
                "active_features": list(features.active_features),
                "active_signal_keys": list(features.active_signal_keys),
                "sha256": features.demand_features_sha256,
            },
            "SELECTOR_TRACE": selector_trace,
            "SUPPLEMENT_PACKET_IDS": list(packet_ids),
            "SUPPLEMENT_PACKET_RECEIPTS": packet_receipts,
            "SUPPLEMENT_SECTION_IDS": [item.section_id for item in sections],
            "SUPPLEMENT_SOURCE_SKILLS": list(dict.fromkeys(
                item.skill_id for item in sections
            )),
            "SUPPLEMENT_SOURCE_SHAS": {
                item.section_id: item.section_content_sha256 for item in sections
            },
            "SUPPLEMENT_RENDER_SHA": rendered.sha256,
            "SUPPLEMENT_CHAR_COUNT": rendered.chars,
            "SUPPLEMENT_TOKEN_ESTIMATE": supplement_tokens,
            "SEMANTIC_DEPENDENCY_CLOSURE_RECEIPT": {
                "edges": closure_rows,
                "cycle_groups": list(cycle_groups),
                "ordering": "dependency-before-dependent_then_resolver-skill-source-order",
                "silent_dependency_drop_count": 0,
            },
            "ACTIONABILITY_DISTRIBUTION": distribution,
            "OVERLAP_CLASSIFICATION": {
                item.section_id: self.index.section_policies[
                    item.section_id
                ].overlap_classification
                for item in sections
            },
            "BUDGET_ALLOCATION": request.budget.receipt(supplement_tokens),
            "TRUNCATION_OCCURRED": "NO",
            "SHEDDING_OCCURRED": "NO",
            "FINAL_HYBRID_ADVISORY_SHA": final_sha,
            "FINAL_HYBRID_MODEL_VISIBLE_CANDIDATE_SHA": final_sha,
            "PRODUCTION_MODEL_INPUT_SHA": request.production_model_input_sha256,
            "RENDER_ORDER": [
                "PROTECTED_NON_SKILL_PREFIX",
                "EXACT_BASELINE_SKILL_FOUNDATION",
                "HYBRID_VERBATIM_SUPPLEMENT",
            ],
            "WRAPPER_VERSION": WRAPPER_VERSION,
            "DELIMITER_VERSION": DELIMITER_VERSION,
            "AUTHORITY_CONTENT_IN_SUPPLEMENT": 0,
            "WRONG_LAYER_SECTION_COUNT": 0,
            "UNSEALED_OWNERSHIP_EXCEPTION_COUNT": 0,
            "UNRESOLVED_CONTRADICTION_COUNT": 0,
            "VERBATIM_MISMATCH": 0,
            "NO_CREATIVE_PARAPHRASE": "YES",
            "NO_SUMMARY_TO_FIT": "YES",
            "HYBRID_MODEL_VISIBLE": "NO",
            "SHADOW_COMPUTE_ONLY": "YES",
            "SHADOW_PASS_NO_GO_FAILURE_REASON": None,
            "SHADOW_RESULT": "PASS",
        }
        unsigned = dict(receipt)
        receipt["RECEIPT_SHA256"] = _canonical_hash(unsigned)
        return HybridSkillContextMaterializationV1(
            baseline_context=request.production_baseline_context,
            supplement_text=rendered.text,
            final_hybrid_advisory=final_advisory,
            ordered_sections=sections,
            receipt=receipt,
        )


def _input_binding_projection(request: HybridShadowInputV1) -> dict[str, object]:
    return {
        "stage": request.stage,
        "substage": request.substage,
        "task_case": request.task_case,
        "task_contract_id": request.task_contract_id,
        "task_contract_schema_sha256": request.task_contract_schema_sha256,
        "creative_demand_class": request.creative_demand_class,
        "demand_signals": dict(request.demand_signals),
        "resolved_skill_ids": list(request.resolved_skill_ids),
        "resolved_skill_source_hashes": list(request.resolved_skill_source_hashes),
        "authority_fact_hashes": list(request.authority_fact_hashes),
        "baseline_context_sha256": _sha_text(request.production_baseline_context),
        "reference_guidance_sha256": _sha_text(
            request.reference_guidance_context
        ),
        "production_model_input_sha256": request.production_model_input_sha256,
    }


def hash_only_hybrid_projection(
    materialization: HybridSkillContextMaterializationV1,
) -> dict[str, object]:
    receipt = materialization.receipt
    return {
        "schema": "HybridSkillContextShadowProjectionV1",
        "SHADOW_RESULT": receipt["SHADOW_RESULT"],
        "RECEIPT_SHA256": receipt["RECEIPT_SHA256"],
        "BASELINE_CONTEXT_SHA": receipt["BASELINE_CONTEXT_SHA"],
        "REFERENCE_GUIDANCE_SHA": receipt["REFERENCE_GUIDANCE_SHA"],
        "DEMAND_FEATURES_SHA": receipt["DEMAND_FEATURES"]["sha256"],
        "SUPPLEMENT_PACKET_IDS": receipt["SUPPLEMENT_PACKET_IDS"],
        "SUPPLEMENT_SECTION_IDS": receipt["SUPPLEMENT_SECTION_IDS"],
        "SUPPLEMENT_SOURCE_SKILLS": receipt["SUPPLEMENT_SOURCE_SKILLS"],
        "SUPPLEMENT_SOURCE_SHAS": receipt["SUPPLEMENT_SOURCE_SHAS"],
        "SUPPLEMENT_RENDER_SHA": receipt["SUPPLEMENT_RENDER_SHA"],
        "SUPPLEMENT_CHAR_COUNT": receipt["SUPPLEMENT_CHAR_COUNT"],
        "SUPPLEMENT_TOKEN_ESTIMATE": receipt["SUPPLEMENT_TOKEN_ESTIMATE"],
        "FINAL_HYBRID_ADVISORY_SHA": receipt["FINAL_HYBRID_ADVISORY_SHA"],
        "FINAL_HYBRID_MODEL_VISIBLE_CANDIDATE_SHA": receipt[
            "FINAL_HYBRID_MODEL_VISIBLE_CANDIDATE_SHA"
        ],
        "PRODUCTION_MODEL_INPUT_SHA": receipt["PRODUCTION_MODEL_INPUT_SHA"],
        "HYBRID_MODEL_VISIBLE": "NO",
        "SHADOW_COMPUTE_ONLY": "YES",
        "MODEL_INPUT_USED": "NO",
        "VALIDATOR_USED": "NO",
        "AUTHORITY_USED": "NO",
        "ROUTER_USED": "NO",
        "RETRY_USED": "NO",
        "RAW_PROMPT_PERSISTED": "NO",
        "RAW_STORY_PERSISTED": "NO",
        "RAW_SKILL_TEXT_PERSISTED": "NO",
    }


def _failure_projection(
    request: HybridShadowInputV1,
    exc: BaseException,
    *,
    code_override: str | None = None,
) -> dict[str, object]:
    code = code_override or (
        exc.code if isinstance(exc, HybridSkillContextError)
        else "UNEXPECTED_COMPILER_EXCEPTION"
    )
    invariant = (
        exc.invariant if isinstance(exc, HybridSkillContextError)
        else "unexpected compiler exception is bounded and fail-open"
    )
    input_sha = _canonical_hash(_input_binding_projection(request))
    message_sha = _sha_text(
        f"{type(exc).__module__}.{type(exc).__qualname__}:{str(exc)}"
    )
    payload: dict[str, object] = {
        "schema": "HybridSkillContextFailureReceiptV1",
        "SHADOW_RESULT": "NO_GO",
        "FAILURE_CODE": code,
        "FAILED_INVARIANT": invariant,
        "INPUT_BINDING_SHA256": input_sha,
        "ERROR_CLASS": type(exc).__name__[:128],
        "ERROR_MESSAGE_SHA256": message_sha,
        "PRODUCTION_MODEL_INPUT_SHA": request.production_model_input_sha256,
        "PRODUCTION_MODEL_INPUT_UNCHANGED": "YES",
        "FAILURE_OBSERVABLE": "YES",
        "NO_EXTERNAL_CALL": "YES",
        "RAW_EXCEPTION_PERSISTED": "NO",
        "TRACEBACK_PERSISTED": "NO",
        "RAW_PROMPT_PERSISTED": "NO",
        "RAW_STORY_PERSISTED": "NO",
        "RAW_SKILL_TEXT_PERSISTED": "NO",
        "HYBRID_MODEL_VISIBLE": "NO",
    }
    payload["FAILURE_RECEIPT_SHA256"] = _canonical_hash(payload)
    return payload


class HybridSkillContextShadowObserverV1:
    """Bounded callable shadow observer; every outcome is hash-only."""

    def __init__(
        self,
        compiler: HybridSkillContextCompilerV1,
        *,
        sink: Callable[[Mapping[str, object]], object] | None = None,
        serializer: Callable[[object], bytes] = _canonical_json_bytes,
    ) -> None:
        self.compiler = compiler
        self.sink = sink
        self.serializer = serializer
        self.observations: list[dict[str, object]] = []

    def __call__(self, request: HybridShadowInputV1) -> dict[str, object]:
        try:
            materialization = self.compiler.materialize(request)
            projection = hash_only_hybrid_projection(materialization)
        except BaseException as exc:  # bounded observer boundary, never dispatch
            projection = _failure_projection(request, exc)
        else:
            try:
                self.serializer(projection)
            except BaseException as exc:
                projection = _failure_projection(
                    request, exc,
                    code_override="RECEIPT_SERIALIZATION_FAILURE",
                )
        if self.sink is not None:
            try:
                self.sink(projection)
            except BaseException as exc:  # sink is observability, never authority
                projection = _failure_projection(
                    request, exc, code_override="RECEIPT_SERIALIZATION_FAILURE",
                )
        self.observations.append(projection)
        return projection
