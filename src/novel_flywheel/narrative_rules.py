from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from novel_flywheel.narrative_ir import (
    ClaimStatus,
    ClaimTransition,
    NarrativeFactGraph,
    StoryClaim,
    parse_narrative_graph,
)


@dataclass(frozen=True)
class NarrativeFinding:
    code: str
    severity: str
    scope: str
    message: str
    claim_ids: tuple[str, ...] = ()
    repairable: bool = True


Rule = Callable[[NarrativeFactGraph], list[NarrativeFinding]]


@dataclass(frozen=True)
class NarrativeRulePack:
    name: str
    rules: tuple[Rule, ...]


def _ordered_claims(graph: NarrativeFactGraph) -> list[StoryClaim]:
    return sorted(graph.claims, key=lambda item: (item.event_order, item.claim_id))


def _claim_conflicts(graph: NarrativeFactGraph) -> list[NarrativeFinding]:
    findings: list[NarrativeFinding] = []
    by_key: dict[tuple[str, str, str, int], list[StoryClaim]] = {}
    for claim in graph.claims:
        if claim.status == ClaimStatus.UNKNOWN:
            continue
        key = (claim.perspective, claim.subject, claim.predicate, claim.event_order)
        by_key.setdefault(key, []).append(claim)
    for key, claims in by_key.items():
        values = {(item.status.value, repr(item.value)) for item in claims}
        if len(values) <= 1:
            continue
        findings.append(NarrativeFinding(
            code="claim_conflict",
            severity="hard",
            scope=":".join(map(str, key)),
            message="同一叙事时点和认知视角存在互相冲突的事实",
            claim_ids=tuple(item.claim_id for item in claims),
        ))
    return findings


def _knowledge_regressions(graph: NarrativeFactGraph) -> list[NarrativeFinding]:
    findings: list[NarrativeFinding] = []
    latest: dict[tuple[str, str, str], StoryClaim] = {}
    for claim in _ordered_claims(graph):
        key = (claim.perspective, claim.subject, claim.predicate)
        previous = latest.get(key)
        if (
            previous is not None
            and previous.status != ClaimStatus.UNKNOWN
            and claim.status == ClaimStatus.UNKNOWN
            and claim.transition not in {ClaimTransition.FORGET, ClaimTransition.RETRACT}
        ):
            findings.append(NarrativeFinding(
                code="knowledge_regression",
                severity="hard",
                scope=":".join(key),
                message="已经明确的事实无失忆、撤回或新证据便退回为未知",
                claim_ids=(previous.claim_id, claim.claim_id),
            ))
        latest[key] = claim
    return findings


def _immutable_identity_changes(graph: NarrativeFactGraph) -> list[NarrativeFinding]:
    findings: list[NarrativeFinding] = []
    actual: dict[tuple[str, str], StoryClaim] = {}
    for claim in _ordered_claims(graph):
        if claim.predicate != "identity.actual" or claim.status == ClaimStatus.UNKNOWN:
            continue
        key = (claim.perspective, claim.subject)
        previous = actual.get(key)
        if previous is not None and previous.value != claim.value:
            findings.append(NarrativeFinding(
                code="actual_identity_changed",
                severity="hard",
                scope=":".join(key),
                message="角色真实身份在没有正式权威变更的情况下发生冲突",
                claim_ids=(previous.claim_id, claim.claim_id),
            ))
        actual[key] = claim
    return findings


def _missing_dependencies(graph: NarrativeFactGraph) -> list[NarrativeFinding]:
    known = {item.claim_id for item in graph.claims}
    findings: list[NarrativeFinding] = []
    for claim in graph.claims:
        missing = tuple(item for item in claim.depends_on if item not in known)
        if missing:
            findings.append(NarrativeFinding(
                code="claim_dependency_missing",
                severity="hard",
                scope=claim.claim_id,
                message="叙事事实引用了不存在的前置事实",
                claim_ids=(claim.claim_id, *missing),
            ))
    return findings


def _requires_support(prefixes: tuple[str, ...], code: str, message: str) -> Rule:
    def validate(graph: NarrativeFactGraph) -> list[NarrativeFinding]:
        return [
            NarrativeFinding(
                code=code,
                severity="hard",
                scope=claim.claim_id,
                message=message,
                claim_ids=(claim.claim_id,),
            )
            for claim in graph.claims
            if claim.predicate.startswith(prefixes)
            and not claim.depends_on and not claim.evidence
        ]
    return validate


CORE_RULE_PACK = NarrativeRulePack("core", (
    _claim_conflicts,
    _knowledge_regressions,
    _immutable_identity_changes,
    _missing_dependencies,
))

GENRE_RULE_PACKS: dict[str, NarrativeRulePack] = {
    "romance": NarrativeRulePack("romance", (
        _requires_support(
            ("relationship.regression",), "romance_relationship_regression",
            "感情关系倒退必须有明确事件依据",
        ),
    )),
    "mystery": NarrativeRulePack("mystery", (
        _requires_support(
            ("mystery.reveal",), "mystery_reveal_without_clue",
            "谜底揭晓必须绑定已铺设或已取得的线索",
        ),
    )),
    "fantasy": NarrativeRulePack("fantasy", (
        _requires_support(
            ("power.gain", "magic.exception"), "fantasy_power_without_basis",
            "能力增长或规则例外必须绑定前提、代价或世界规则证据",
        ),
    )),
    "scifi": NarrativeRulePack("scifi", (
        _requires_support(
            ("technology.capability",), "scifi_capability_without_premise",
            "技术能力必须绑定既有技术前提或证据",
        ),
    )),
    "historical": NarrativeRulePack("historical", (
        _requires_support(
            ("status.change",), "historical_status_without_cause",
            "身份、爵位或礼法地位变化必须有正式因果依据",
        ),
    )),
    "rebirth": NarrativeRulePack("rebirth", (
        _requires_support(
            ("foreknowledge",), "rebirth_foreknowledge_without_source",
            "前世知识必须绑定前世经历或已发生的信息来源",
        ),
    )),
    "comedy": NarrativeRulePack("comedy", (
        _requires_support(
            ("misunderstanding",), "comedy_misunderstanding_without_gap",
            "误会必须绑定可验证的信息差，不能依赖角色突然降智",
        ),
    )),
}


GENRE_ALIASES = {
    "言情": "romance", "古言": "romance", "现代言情": "romance",
    "悬疑": "mystery", "推理": "mystery",
    "玄幻": "fantasy", "仙侠": "fantasy", "奇幻": "fantasy",
    "科幻": "scifi", "历史": "historical", "古代": "historical",
    "重生": "rebirth", "喜剧": "comedy", "轻喜剧": "comedy",
}


def canonical_genres(values: Iterable[str]) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        normalized = str(value or "").strip().casefold()
        genre = GENRE_ALIASES.get(normalized, normalized)
        if genre in GENRE_RULE_PACKS and genre not in result:
            result.append(genre)
    return tuple(result)


def validate_narrative_graph(
    value: NarrativeFactGraph | object, *, genres: Iterable[str] = (),
) -> list[NarrativeFinding]:
    graph = value if isinstance(value, NarrativeFactGraph) else parse_narrative_graph(value)
    packs = [CORE_RULE_PACK, *(
        GENRE_RULE_PACKS[name] for name in canonical_genres(genres)
    )]
    findings: list[NarrativeFinding] = []
    seen: set[tuple[str, str, tuple[str, ...]]] = set()
    for pack in packs:
        for rule in pack.rules:
            for finding in rule(graph):
                identity = (finding.code, finding.scope, finding.claim_ids)
                if identity not in seen:
                    findings.append(finding)
                    seen.add(identity)
    return findings
