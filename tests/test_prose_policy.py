import importlib
import importlib.util
import json
from pathlib import Path


def prose_policy_module():
    spec = importlib.util.find_spec("novel_flywheel.prose_policy")
    assert spec is not None, "project prose policy module is not implemented"
    return importlib.import_module("novel_flywheel.prose_policy")


def write_active_baseline(project_path: Path, data: dict) -> None:
    folder = project_path / "learning"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "prose_baseline.json").write_text(json.dumps({
        "status": "active",
        "version": 1,
        "data": data,
    }, ensure_ascii=False), encoding="utf-8")


def test_old_project_without_style_artifacts_uses_conservative_defaults(tmp_path) -> None:
    module = prose_policy_module()

    policy = module.load_prose_validation_policy(tmp_path)

    assert policy.source_ids == ()
    assert policy.authorized_short_beats == frozenset()
    assert policy.conflicts == ()
    assert policy.absolute_ratio_floor == 0.10
    assert policy.minimum_new_units == 3


def test_confirmed_baseline_authorizes_named_short_beats_without_rewriting_project(
    tmp_path,
) -> None:
    module = prose_policy_module()
    write_active_baseline(tmp_path, {
        "sentence_rhythm": ["在情绪转折、信息揭示和喜剧落点使用短句与留白。"],
    })
    before = (tmp_path / "learning" / "prose_baseline.json").read_bytes()

    policy = module.load_prose_validation_policy(tmp_path)

    assert policy.authorized_short_beats == frozenset({
        "emotion_shift", "information_reveal", "comic_turn",
    })
    assert policy.conflicts == ()
    assert policy.source_ids == ("prose_baseline:1",)
    assert (tmp_path / "learning" / "prose_baseline.json").read_bytes() == before


def test_project_style_profile_can_authorize_a_local_beat(tmp_path) -> None:
    module = prose_policy_module()
    (tmp_path / "style-profile.md").write_text(
        "# 文风\n\n- 句子节奏：关系变化和悬念建立时可以使用短句。\n",
        encoding="utf-8",
    )

    policy = module.load_prose_validation_policy(tmp_path)

    assert policy.authorized_short_beats == frozenset({
        "relationship_change", "suspense_turn",
    })
    assert policy.source_ids == ("style-profile",)


def test_market_advice_never_authorizes_soft_override(tmp_path) -> None:
    module = prose_policy_module()
    (tmp_path / "market-reference.md").write_text("全篇大量使用短句。", encoding="utf-8")

    policy = module.load_prose_validation_policy(tmp_path)

    assert policy.authorized_short_beats == frozenset()
    assert policy.source_ids == ()


def test_ambiguous_or_conflicting_rules_fail_closed(tmp_path) -> None:
    module = prose_policy_module()
    write_active_baseline(tmp_path, {
        "sentence_rhythm": ["全篇短句为主。", "禁止使用短句。"],
    })

    policy = module.load_prose_validation_policy(tmp_path)

    assert policy.authorized_short_beats == frozenset()
    assert policy.conflicts == ("style_policy_conflict",)


def test_optional_structured_policy_accepts_only_known_beat_ids(tmp_path) -> None:
    module = prose_policy_module()
    write_active_baseline(tmp_path, {
        "validation_policy": {
            "authorized_short_beats": [
                "information_reveal", "relationship_change", "unknown_genre_beat",
            ],
        },
    })

    policy = module.load_prose_validation_policy(tmp_path)

    assert policy.authorized_short_beats == frozenset({
        "information_reveal", "relationship_change",
    })


def test_narrative_beat_tags_come_from_structured_state_not_genre_words() -> None:
    module = prose_policy_module()

    tags = module.infer_narrative_beat_tags({
        "reveals": ["身份已揭开"],
        "relationship_changed": True,
        "payoffs": [{"id": "payoff-1"}],
        "scenes": [{"state_changes": [{"evidence": "她决定离开"}]}],
        "genre": "古言悬疑科幻",
    })

    assert tags == frozenset({
        "information_reveal", "relationship_change", "suspense_turn", "emotion_shift",
    })
