import hashlib
import re
from collections.abc import Iterable


class ConstraintPromptCompactor:
    _HARD = (
        "必须", "不能", "不得", "禁止", "避免", "不可", "至少", "只允许",
        "must", "never", "do not", "cannot", "required", "forbidden", "avoid",
    )

    def __init__(self, max_chars: int = 7000) -> None:
        self.max_chars = max_chars
        self._cache: dict[str, str] = {}

    def compact(self, text: str) -> str:
        key = hashlib.sha256(text.encode()).hexdigest()
        if key in self._cache:
            return self._cache[key]
        candidates = []
        for index, line in enumerate(text.splitlines()):
            stripped = line.strip()
            if not stripped:
                continue
            lowered = stripped.lower()
            if any(marker in lowered for marker in self._HARD):
                priority = 0
            elif stripped.startswith("#"):
                priority = 1
            elif re.match(r"^(?:[-*+] |\d+[.)] )", stripped):
                priority = 2
            else:
                continue
            candidates.append((priority, index, stripped))

        prefix = "COMPACT POLISH CONSTRAINTS:\n"
        used = len(prefix)
        selected = []
        for priority in range(3):
            group = [item for item in candidates if item[0] == priority]
            ordered = []
            left, right = 0, len(group) - 1
            while left <= right:
                ordered.append(group[left])
                if left != right:
                    ordered.append(group[right])
                left += 1
                right -= 1
            for _, index, line in ordered:
                cost = len(line) + 1
                if used + cost <= self.max_chars:
                    selected.append((index, line))
                    used += cost
        compact = prefix + "\n".join(line for _, line in sorted(selected))
        if not selected or len(compact) >= len(text):
            compact = text
        self._cache[key] = compact
        return compact


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
