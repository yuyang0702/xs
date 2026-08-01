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

    _STAGE_SECTIONS = {
        "confirmed story facts (take precedence over older project notes)": 0,
        "program-enforced locked story facts": 0,
        "platform hard rules": 0,
        "confirmed outline event ids": 1,
        "current confirmed outline": 1,
        "confirmed long-form execution plan": 1,
        "executable prose baseline": 2,
        "confirmed creative blueprint": 3,
        "character voice profiles": 4,
        "character knowledge boundaries": 4,
        "scene briefs": 4,
        "short story causal chain": 4,
        "advisory market baseline": 5,
        "market advice (optional)": 5,
    }

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

    def compact_for_stage(self, text: str, *, stage: str, focus: str = "") -> str:
        """Reserve room for confirmed story material before generic compression."""
        key = hashlib.sha256(
            f"stage\0{stage}\0{focus}\0{text}".encode()
        ).hexdigest()
        if key in self._cache:
            return self._cache[key]

        sections = self._top_level_sections(text)
        confirmed = [
            (self._STAGE_SECTIONS[title.casefold()], index, title, body)
            for index, (title, body) in enumerate(sections)
            if title.casefold() in self._STAGE_SECTIONS
        ]
        if not confirmed:
            return self.compact(text)

        confirmed_titles = {title.casefold() for _, _, title, _ in confirmed}
        general = "\n\n".join(
            f"# {title}\n{body}" for title, body in sections
            if title.casefold() not in confirmed_titles
        )
        generic_budget = min(1200, max(400, self.max_chars // 5))
        generic = ConstraintPromptCompactor(generic_budget).compact(general)
        if generic == general and len(generic) > generic_budget:
            generic = generic[:generic_budget]

        prefix = f"CONFIRMED CONTEXT FOR {stage.upper()}:\n"
        chunks = [prefix]
        used = len(prefix)
        ordered = sorted(confirmed)
        minimum_body = 120
        for position, (_priority, _index, title, body) in enumerate(ordered):
            remaining = self.max_chars - used
            if remaining <= len(title) + 6:
                break
            future_minimum = sum(
                len(future_title) + minimum_body + 4
                for _, _, future_title, _ in ordered[position + 1:]
            )
            available = max(len(title) + minimum_body + 4, remaining - future_minimum)
            section_budget = min(self._section_budget(title, stage), available, remaining)
            excerpt = self._focused_excerpt(body, focus, max(80, section_budget - len(title) - 4))
            chunk = f"# {title}\n{excerpt.strip()}\n"
            if len(chunk) <= remaining:
                chunks.append(chunk)
                used += len(chunk)

        if generic.strip() and used < self.max_chars:
            remaining = self.max_chars - used
            chunks.append("\n" + generic[:remaining])
        compact = "".join(chunks)[:self.max_chars]
        self._cache[key] = compact
        return compact

    @staticmethod
    def _top_level_sections(text: str) -> list[tuple[str, str]]:
        matches = list(re.finditer(r"(?m)^# ([^\r\n]+)\s*$", text))
        if not matches:
            return []
        sections = [
            (
                match.group(1).strip(),
                text[match.end(): matches[index + 1].start() if index + 1 < len(matches) else len(text)].strip(),
            )
            for index, match in enumerate(matches)
        ]
        preamble = text[:matches[0].start()].strip()
        return ([('General Constraints', preamble)] if preamble else []) + sections

    @staticmethod
    def _section_budget(title: str, stage: str) -> int:
        key = title.casefold()
        if "outline" in key or "execution plan" in key:
            return 3200 if stage == "draft" else 2600
        if "story facts" in key or "locked" in key:
            return 1400
        if "prose baseline" in key or "creative blueprint" in key:
            return 1800
        if "voice" in key or "knowledge" in key or "scene briefs" in key:
            return 1200
        return 900

    @staticmethod
    def _focused_excerpt(body: str, focus: str, limit: int) -> str:
        if len(body) <= limit:
            return body
        blocks = [item.strip() for item in re.split(r"\n\s*\n", body) if item.strip()]
        if not blocks:
            return body[:limit]
        terms = {
            item.casefold() for item in re.findall(r"[A-Za-z0-9_-]{3,}|[\u3400-\u9fff]{2,6}", focus)
        }
        ranked = sorted(
            range(len(blocks)),
            key=lambda index: (
                -sum(term in blocks[index].casefold() for term in terms), index,
            ),
        )
        chosen = {0, len(blocks) - 1}
        chosen.update(ranked[:4])
        result = ""
        for index in sorted(chosen):
            block = blocks[index]
            addition = ("\n\n" if result else "") + block
            if len(result) + len(addition) > limit:
                continue
            result += addition
        return result or body[:limit]


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
