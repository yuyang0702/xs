import hashlib
import re
from collections.abc import Iterable


class SkillPromptCompactor:
    _FRONTMATTER = re.compile(
        r"(?ms)^---\s*\n(?=(?:name|description):).*?\n---\s*(?:\n|$)"
    )
    _SKIP = (
        "example", "examples", "示例", "改写前", "改写后", "before", "after",
        "trigger", "permission", "reference", "when to use",
    )
    _HARD = (
        "must", "never", "do not", "cannot", "preserve", "avoid", "required",
        "必须", "绝不", "不要", "不能", "保留", "避免", "禁止", "硬规则", "核心规则",
    )

    def __init__(self, max_chars: int = 9000) -> None:
        self.max_chars = max_chars
        self._cache: dict[tuple[str, ...], str] = {}

    def compact(self, full_prompt: str, receipts: Iterable[object]) -> str:
        hashes = tuple(str(getattr(item, "content_hash", "")) for item in receipts)
        key = hashes or (hashlib.sha256(full_prompt.encode()).hexdigest(),)
        if key in self._cache:
            return self._cache[key]
        try:
            compact = self._build(full_prompt)
        except (TypeError, ValueError):
            compact = full_prompt
        if not compact.removeprefix("COMPACT SKILL EXECUTION RULES:\n").strip() or len(compact) >= len(full_prompt):
            compact = full_prompt
        self._cache[key] = compact
        return compact

    def _build(self, prompt: str) -> str:
        if not isinstance(prompt, str):
            raise TypeError("Skill prompt must be text")
        text = self._FRONTMATTER.sub("", prompt)
        candidates: list[tuple[int, int, str]] = []
        in_fence = False
        for index, line in enumerate(text.splitlines()):
            stripped = line.strip()
            if stripped.startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence or not stripped or stripped.startswith(">"):
                continue
            lowered = stripped.lower()
            if any(marker in lowered for marker in self._SKIP):
                continue
            if any(marker in lowered for marker in self._HARD):
                priority = 0
            elif stripped.startswith("#"):
                priority = 1
            elif re.match(r"^(?:[-*+] |\d+[.)] )", stripped):
                priority = 2
            else:
                continue
            candidates.append((priority, index, stripped))

        selected: list[tuple[int, str]] = []
        used = 0
        for _, index, line in sorted(candidates):
            cost = len(line) + 1
            if used + cost > self.max_chars:
                continue
            selected.append((index, line))
            used += cost
        body = "\n".join(line for _, line in sorted(selected))
        return "COMPACT SKILL EXECUTION RULES:\n" + body
