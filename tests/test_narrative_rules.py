import pytest

from novel_flywheel.narrative_ir import NarrativeFactGraph, StoryClaim
from novel_flywheel.narrative_rules import (
    GENRE_RULE_PACKS,
    canonical_genres,
    validate_narrative_graph,
)


def claim(claim_id: str, **values) -> StoryClaim:
    return StoryClaim(claim_id=claim_id, subject="花穗", predicate="identity.actual", **values)


def test_known_public_identity_cannot_silently_regress_to_unknown() -> None:
    graph = NarrativeFactGraph(claims=[
        claim(
            "confession", value="花穗", perspective="public", event_order=4,
            transition="reveal", authority="formal", evidence="花穗公开坦白",
        ),
        claim(
            "adoption", value=None, perspective="public", event_order=6,
            status="unknown", transition="question", authority="candidate",
            evidence="花穗是不是蕙芷已经问不出来了",
        ),
    ])

    findings = validate_narrative_graph(graph)

    assert [item.code for item in findings] == ["knowledge_regression"]
    assert findings[0].claim_ids == ("confession", "adoption")


def test_explicit_forgetting_or_retraction_is_not_a_silent_regression() -> None:
    graph = NarrativeFactGraph(claims=[
        claim("known", value="花穗", perspective="裴砚行", event_order=4),
        claim(
            "forgot", value=None, perspective="裴砚行", event_order=8,
            status="unknown", transition="forget", evidence="记忆术代价",
        ),
    ])

    assert validate_narrative_graph(graph) == []


def test_actual_identity_is_immutable_but_character_belief_may_be_revised() -> None:
    graph = NarrativeFactGraph(claims=[
        claim("actual-1", value="花穗", event_order=1, authority="formal"),
        claim("actual-2", value="蕙芷", event_order=2, authority="candidate"),
        StoryClaim(
            claim_id="belief-1", subject="花穗", predicate="identity.belief",
            perspective="裴砚行", value="蕙芷", event_order=1,
        ),
        StoryClaim(
            claim_id="belief-2", subject="花穗", predicate="identity.belief",
            perspective="裴砚行", value="花穗", event_order=2,
            transition="revise", evidence="公开坦白",
        ),
    ])

    assert {item.code for item in validate_narrative_graph(graph)} == {
        "actual_identity_changed",
    }


@pytest.mark.parametrize(("genre", "predicate", "code"), [
    ("言情", "relationship.regression", "romance_relationship_regression"),
    ("悬疑", "mystery.reveal", "mystery_reveal_without_clue"),
    ("玄幻", "power.gain", "fantasy_power_without_basis"),
    ("科幻", "technology.capability", "scifi_capability_without_premise"),
    ("历史", "status.change", "historical_status_without_cause"),
    ("重生", "foreknowledge", "rebirth_foreknowledge_without_source"),
    ("喜剧", "misunderstanding", "comedy_misunderstanding_without_gap"),
])
def test_genre_packs_add_constraints_without_disabling_core_rules(
    genre: str, predicate: str, code: str,
) -> None:
    graph = NarrativeFactGraph(claims=[StoryClaim(
        claim_id="genre-event", subject="主角", predicate=predicate,
        value="发生", event_order=2,
    )])

    findings = validate_narrative_graph(graph, genres=[genre])

    assert code in {item.code for item in findings}
    assert canonical_genres([genre])[0] in GENRE_RULE_PACKS


def test_genre_rule_accepts_hash_bound_or_evidenced_support() -> None:
    graph = NarrativeFactGraph(claims=[
        StoryClaim(
            claim_id="clue", subject="凶案", predicate="mystery.clue",
            value="泥印", event_order=1, evidence="门槛留下泥印",
        ),
        StoryClaim(
            claim_id="reveal", subject="凶案", predicate="mystery.reveal",
            value="园丁", event_order=4, depends_on=["clue"],
        ),
    ])

    assert validate_narrative_graph(graph, genres=["mystery"]) == []
