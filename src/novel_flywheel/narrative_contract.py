from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
import unicodedata

from novel_flywheel.projects import Project
from novel_flywheel.storage import atomic_write


FIRST_PERSON_MARKERS = (
    "first", "first-person", "first_person", "第一人称", "第一视角",
)
THIRD_PERSON_MARKERS = (
    "third", "third-person", "third_person", "第三人称", "第三视角",
)
NARRATOR_ROLES = {"narrator", "叙述者", "叙事者"}
PROTAGONIST_ROLES = {
    "protagonist", "main", "lead", "hero", "heroine", "主角", "女主", "男主",
}


@dataclass(frozen=True)
class NarrativeContract:
    status: str
    mode: str
    narrator_character_id: str = ""
    narrator_name: str = ""
    self_reference: str = ""
    allow_subject_ellipsis: bool = True
    other_minds: str = "observable_or_attributed_only"
    source: str = ""
    candidates: tuple[dict[str, str], ...] = ()

    def payload(self) -> dict:
        value = asdict(self)
        value["candidates"] = [dict(item) for item in self.candidates]
        return value


def _normalized(value: object) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip().lower()


def _viewpoint_mode(metadata: dict) -> str:
    pov = _normalized(metadata.get("pov") or metadata.get("perspective"))
    if any(marker in pov for marker in THIRD_PERSON_MARKERS):
        return "third_person_limited"
    if any(marker in pov for marker in FIRST_PERSON_MARKERS):
        return "first_person_limited"
    combined = _normalized(
        "\n".join(str(metadata.get(key) or "") for key in ("premise", "story_requirements"))
    )
    if any(marker in combined for marker in THIRD_PERSON_MARKERS):
        return "third_person_limited"
    if any(marker in combined for marker in FIRST_PERSON_MARKERS):
        return "first_person_limited"
    return "third_person_limited"


def _frontmatter_scalar(text: str, key: str) -> str:
    if not text.startswith("---"):
        return ""
    parts = text.split("---", 2)
    if len(parts) != 3:
        return ""
    match = re.search(
        rf"(?mi)^[ \t]*{re.escape(key)}[ \t]*:[ \t]*(?P<value>[^\r\n]+)",
        parts[1],
    )
    return str(match.group("value") if match else "").strip().strip("\"'")


def _characters(project_path: Path) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for path in sorted((project_path / "characters").glob("*.md")):
        if path.name == "_index.md":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        name = _frontmatter_scalar(text, "name")
        role = _normalized(_frontmatter_scalar(text, "role"))
        if name:
            result.append({"id": path.stem, "name": name, "role": role})
    return result


def _outline_text(project: Project) -> str:
    values = [str(project.metadata.get("premise") or "")]
    for relative in ("plot/outline.md", "story.md"):
        path = project.path / relative
        try:
            values.append(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError):
            pass
    return "\n".join(values)


def _explicit_contract(metadata: dict, characters: list[dict[str, str]]) -> NarrativeContract | None:
    raw = metadata.get("narrative_contract")
    raw = raw if isinstance(raw, dict) else {}
    character_id = str(
        raw.get("narrator_character_id")
        or metadata.get("narrator_character_id")
        or ""
    ).strip()
    name = str(raw.get("narrator_name") or metadata.get("narrator_name") or "").strip()
    if character_id and not name:
        name = next(
            (item["name"] for item in characters if item["id"] == character_id), "",
        )
    if name and not character_id:
        matches = [item for item in characters if item["name"] == name]
        if len(matches) == 1:
            character_id = matches[0]["id"]
    if not character_id or not name:
        return None
    return NarrativeContract(
        status="ready",
        mode=str(raw.get("mode") or "first_person_limited"),
        narrator_character_id=character_id,
        narrator_name=name,
        self_reference=str(raw.get("self_reference") or "我"),
        allow_subject_ellipsis=bool(raw.get("allow_subject_ellipsis", True)),
        other_minds=str(raw.get("other_minds") or "observable_or_attributed_only"),
        source="project_binding",
    )


def resolve_narrative_contract(project: Project) -> NarrativeContract:
    mode = _viewpoint_mode(project.metadata)
    if not mode.startswith("first_person"):
        return NarrativeContract(status="ready", mode=mode, source="project_viewpoint")

    characters = _characters(project.path)
    explicit = _explicit_contract(project.metadata, characters)
    if explicit is not None:
        return explicit

    outline = _outline_text(project)
    named = [
        item for item in characters
        if re.search(
            rf"(?:第一人称|第一视角)[^\r\n]{{0,24}}{re.escape(item['name'])}"
            rf"|{re.escape(item['name'])}[^\r\n]{{0,24}}(?:第一人称|第一视角)",
            outline,
        )
    ]
    if len(named) == 1:
        selected = named[0]
        source = "outline_named_viewpoint"
    else:
        narrators = [item for item in characters if item["role"] in NARRATOR_ROLES]
        protagonists = [item for item in characters if item["role"] in PROTAGONIST_ROLES]
        candidates = narrators or protagonists
        if len(candidates) != 1:
            return NarrativeContract(
                status="needs_confirmation",
                mode=mode,
                source="ambiguous_character_roles",
                candidates=tuple(dict(item) for item in candidates or characters),
            )
        selected = candidates[0]
        source = "unique_narrator_role" if narrators else "unique_protagonist_role"
    return NarrativeContract(
        status="ready",
        mode=mode,
        narrator_character_id=selected["id"],
        narrator_name=selected["name"],
        self_reference="我",
        source=source,
    )


def narrative_contract_sha256(contract: NarrativeContract) -> str:
    return hashlib.sha256(json.dumps(
        contract.payload(), ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def ensure_narrative_contract(project: Project) -> NarrativeContract:
    """Resolve and expose the current contract without making it a second canon."""
    contract = resolve_narrative_contract(project)
    source_parts = [json.dumps(
        {
            "pov": project.metadata.get("pov"),
            "premise": project.metadata.get("premise"),
            "narrative_contract": project.metadata.get("narrative_contract"),
        },
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )]
    for path in sorted((project.path / "characters").glob("*.md")):
        try:
            source_parts.append(path.name + "\n" + path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError):
            continue
    atomic_write(
        project.path / "memory" / "narrative-contract.json",
        json.dumps({
            "version": 1,
            "source_sha256": hashlib.sha256(
                "\n\n".join(source_parts).encode("utf-8"),
            ).hexdigest(),
            "contract_sha256": narrative_contract_sha256(contract),
            "contract": contract.payload(),
        }, ensure_ascii=False, indent=2) + "\n",
    )
    return contract


def confirm_narrative_contract(
    project: Project, narrator_character_id: str,
) -> NarrativeContract:
    character_id = str(narrator_character_id or "").strip()
    characters = _characters(project.path)
    selected = next((item for item in characters if item["id"] == character_id), None)
    if selected is None:
        raise ValueError("选择的第一人称叙述者不在当前作品人物档案中")
    if not _viewpoint_mode(project.metadata).startswith("first_person"):
        raise ValueError("当前作品不是第一人称项目，不需要绑定第一人称叙述者")
    metadata = {
        **project.metadata,
        "narrative_contract": {
            "mode": "first_person_limited",
            "narrator_character_id": selected["id"],
            "narrator_name": selected["name"],
            "self_reference": "我",
            "allow_subject_ellipsis": True,
            "other_minds": "observable_or_attributed_only",
        },
    }
    atomic_write(
        project.path / "project.json",
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
    )
    project.metadata.clear()
    project.metadata.update(metadata)
    return ensure_narrative_contract(project)


def render_narrative_contract(contract: NarrativeContract) -> str:
    if not contract.mode.startswith("first_person"):
        return f"叙述合同：{contract.mode}；不启用第一人称叙述者绑定。"
    if contract.status != "ready":
        names = "、".join(item.get("name", "") for item in contract.candidates)
        return f"叙述合同待确认：第一人称叙述者无法唯一确定；候选为 {names or '无'}。"
    return (
        f"叙述合同：{contract.mode}；叙述者={contract.narrator_name}"
        f"（{contract.narrator_character_id}）；自称={contract.self_reference}。"
        f"{contract.narrator_name}自身必须用“{contract.self_reference}”叙述，允许自然省略主语，"
        f"不得把{contract.narrator_name}写成“{contract.narrator_name}/她”或"
        f"“{contract.narrator_name}/他”的第三人称叙述对象。"
        "其他人物的内心只能通过叙述者可观察到的言行、已知事实或带保留的推断呈现。"
        "规划材料即使使用人物姓名，也只提供事件权威，不能覆盖正文的人称合同。"
    )


def first_person_prose_issues(
    contract: object, prose: str,
) -> list[dict[str, str]]:
    status = str(getattr(contract, "status", "ready") or "ready")
    mode = str(
        getattr(contract, "mode", "")
        or getattr(contract, "narrative_mode", "")
    )
    if status != "ready" or not mode.startswith("first_person"):
        return []
    visible = str(prose or "").strip()
    if not visible:
        return []
    issues: list[dict[str, str]] = []
    self_reference = str(getattr(contract, "self_reference", "") or "我")
    narrative_only = re.sub(
        r"“.*?”|‘.*?’|「.*?」|『.*?』|\".*?\"", "", visible,
        flags=re.DOTALL,
    )
    self_count = narrative_only.count(self_reference)
    narrator_name = str(getattr(contract, "narrator_name", "") or "")
    narrator_count = narrative_only.count(narrator_name) if narrator_name else 0
    if self_count == 0 and narrator_count >= 2:
        issues.append({
            "code": "first_person_self_reference_missing",
            "message": f"第一人称正文没有使用叙述者自称“{self_reference}”",
        })
    if narrator_count >= 2 and self_count == 0:
        issues.append({
            "code": "narrator_third_person_drift",
            "message": f"正文持续把叙述者{narrator_name}写成第三人称对象",
        })
    return issues
