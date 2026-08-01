from dataclasses import dataclass

from novel_flywheel.prompts import EXPANSION_CONTRACT, REQUIRED_SKILLS
from novel_flywheel.skill_prompts import ConstraintPromptCompactor, SkillPromptCompactor


@dataclass(frozen=True)
class Receipt:
    content_hash: str


def test_expansion_contract_requires_scene_state_and_full_review() -> None:
    for field in (
        "purpose", "target_han", "entry_state", "exit_state", "anchor",
        "operation", "requires_full_review", "time", "evidence_source",
        "transition", "new_facts",
    ):
        assert field in EXPANSION_CONTRACT
    assert "只能从 anchor_candidates" in EXPANSION_CONTRACT
    assert "非空字符串列表" in EXPANSION_CONTRACT
    assert "背景说明" in EXPANSION_CONTRACT
    assert REQUIRED_SKILLS["revision_plan"] == [
        "revision-continuity", "plot-structure",
    ]
    assert REQUIRED_SKILLS["draft"] == [
        "chapter-writing", "novel-writing", "dialogue",
    ]


def test_compactor_keeps_hard_rules_and_removes_examples() -> None:
    prompt = """---
name: prose
triggers: [rewrite]
---
# Prose Skill
## Hard Rules
- Never change established plot facts.
- 必须保留人物独有的说话节奏。
## Examples
改写前：这是一个需要删除的长示例。
> 示例正文不应发送给模型。
改写后：另一个示例。
## Working Pattern
1. Avoid summary when the scene needs action.
"""

    compact = SkillPromptCompactor(max_chars=4000).compact(prompt, [Receipt("hash-a")])

    assert "Never change established plot facts" in compact
    assert "必须保留人物独有的说话节奏" in compact
    assert "Avoid summary" in compact
    assert "长示例" not in compact
    assert "triggers" not in compact


def test_compactor_preserves_multiple_skills_and_markdown_rules() -> None:
    prompt = """---
name: first
---
# First Skill
## 核心规则速查
- 删除填充短语。
---
---
name: second
---
# Second Skill
## Hard Rules
### Reader Knowledge Is Not Author Knowledge
- Never assume the reader already knows.
---
---
name: third
---
# Dialogue Skill
- **Every character sounds different** — preserve their rhythm.
"""

    compact = SkillPromptCompactor(max_chars=4000).compact(
        prompt, [Receipt("one"), Receipt("two"), Receipt("three")],
    )

    assert "删除填充短语" in compact
    assert "Reader Knowledge Is Not Author Knowledge" in compact
    assert "Every character sounds different" in compact


def test_compactor_cache_is_keyed_by_skill_hash() -> None:
    compactor = SkillPromptCompactor(max_chars=4000)
    first = compactor.compact("# Rules\n- Never remove A.", [Receipt("hash-a")])
    cached = compactor.compact("# Rules\n- Never remove B.", [Receipt("hash-a")])
    rebuilt = compactor.compact("# Rules\n- Never remove B.", [Receipt("hash-b")])

    assert cached == first
    assert "remove B" in rebuilt


def test_compactor_falls_back_when_no_execution_rules_are_found() -> None:
    prompt = "A plain skill description without structured execution rules."

    assert SkillPromptCompactor().compact(prompt, [Receipt("hash-a")]) == prompt


def test_stage_constraint_compactor_reserves_confirmed_writing_context() -> None:
    constraints = "\n\n".join((
        "# General Notes\n" + "background filler\n" * 400,
        "# CONFIRMED STORY FACTS (take precedence over older project notes)\n"
        "- ending: The heroine leaves alone.",
        "# Confirmed Outline Event IDs\n- EV-a1b2c3d4: The sealed letter is opened",
        "# Current Confirmed Outline\n"
        "## Opening\nThe heroine receives the sealed letter.\n\n"
        "## Ending\nShe opens it and learns why her friend died.",
        "# Executable Prose Baseline\n"
        '{"sentence_rhythm":["Alternate long and short sentences."],'
        '"dialogue":["Every reply changes information or relationship."]}',
        "# Confirmed Creative Blueprint\n"
        '{"mechanisms":[{"name":"Delayed answer",'
        '"transfer_guidance":"Keep the letter unresolved until the final turn."}]}',
    ))

    compact = ConstraintPromptCompactor(max_chars=5200).compact_for_stage(
        constraints, stage="polish", focus="EV-a1b2c3d4 sealed letter final turn",
    )

    assert "The heroine leaves alone" in compact
    assert "The sealed letter is opened" in compact
    assert "She opens it and learns why her friend died" in compact
    assert "Alternate long and short sentences" in compact
    assert "Keep the letter unresolved until the final turn" in compact
    assert "background filler" not in compact
    assert len(compact) <= 5400


def test_stage_constraint_compactor_does_not_let_long_outline_hide_style() -> None:
    constraints = "\n\n".join((
        "# CONFIRMED STORY FACTS (take precedence over older project notes)\n"
        + "The confirmed fact must remain.\n" * 200,
        "# Current Confirmed Outline\n"
        + "The long outline continues through another event.\n" * 400,
        "# Executable Prose Baseline\nKeep the confirmed sentence rhythm.",
        "# Confirmed Creative Blueprint\nDelay the confirmed answer until the ending.",
    ))

    compact = ConstraintPromptCompactor(max_chars=4000).compact_for_stage(
        constraints, stage="polish", focus="ending",
    )

    assert "The confirmed fact must remain" in compact
    assert "The long outline continues" in compact
    assert "Keep the confirmed sentence rhythm" in compact
    assert "Delay the confirmed answer until the ending" in compact
    assert len(compact) <= 4000


def test_stage_constraint_compactor_keeps_rules_before_first_heading() -> None:
    constraints = (
        "Never change the confirmed first-person viewpoint.\n\n"
        "# Current Confirmed Outline\nThe protagonist opens the door.\n\n"
        "# Executable Prose Baseline\nKeep the narration restrained."
    )

    compact = ConstraintPromptCompactor(max_chars=2000).compact_for_stage(
        constraints, stage="polish", focus="opens the door",
    )

    assert "Never change the confirmed first-person viewpoint" in compact
    assert "The protagonist opens the door" in compact
    assert "Keep the narration restrained" in compact


def test_constraint_compactor_keeps_hard_rules_and_bounds_repeated_context() -> None:
    constraints = "\n".join([
        "# 通用规则",
        *[f"普通背景说明 {index}" for index in range(200)],
        "- 必须保持人物已知信息边界。",
        "- 不能修改已经成立的剧情事实。",
        "# 项目规则",
        "- 女主最终不能原谅男主。",
    ])

    compact = ConstraintPromptCompactor(max_chars=180).compact(constraints)

    assert len(compact) <= 220
    assert "必须保持人物已知信息边界" in compact
    assert "不能修改已经成立的剧情事实" in compact
    assert "女主最终不能原谅男主" in compact
    assert "普通背景说明 100" not in compact
