from dataclasses import dataclass

from novel_flywheel.skill_prompts import ConstraintPromptCompactor, SkillPromptCompactor


@dataclass(frozen=True)
class Receipt:
    content_hash: str


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
