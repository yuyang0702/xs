import json
import re
import uuid
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel, ConfigDict, Field

from novel_flywheel.db import Database, WIZARD_MUTATION_LOCK
from novel_flywheel.projects import Project, ProjectCreate, ProjectStore
from novel_flywheel.skills import Skill, SkillGate
from novel_flywheel.storage import atomic_write


class FormField(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-zA-Z0-9_.-]+$")
    label: str = Field(min_length=1)
    type: Literal["text", "textarea", "number", "select", "multiselect", "boolean"]
    required: bool = False
    lockable: bool = True
    options: list[str] = Field(default_factory=list)
    default: object | None = None
    help: str = ""


class FormStep(BaseModel):
    title: str = Field(min_length=1)
    fields: list[FormField]
    skill_name: str | None = None
    skill_hash: str | None = None


CORE_STEP = FormStep(title="作品定位", fields=[
    FormField(id="title", label="作品名", type="text", required=True),
    FormField(id="genre", label="题材", type="text", required=True),
    FormField(id="sub_genre", label="子类型", type="text"),
    FormField(id="premise", label="核心创意或梗概", type="textarea", required=True),
    FormField(id="target_words", label="目标字数", type="number", required=True, default=100000),
    FormField(id="platform_profile_id", label="准备发布到哪里", type="select",
              default="none", options=["none", "zhihu-salt-short"],
              help="选择后只调整后续创作检查，不会改动你的正文。"),
    FormField(id="audience", label="目标读者", type="text"),
    FormField(id="market_baseline_enabled", label="同类市场建议", type="select",
              default="enabled", options=["enabled", "disabled"]),
    FormField(id="market_baseline_key", label="市场样本组", type="select", options=[]),
    FormField(id="pov", label="叙事视角", type="select", default="third-limited",
              options=["first", "third-limited", "omniscient"]),
    FormField(id="tense", label="时态", type="select", default="past", options=["past", "present"]),
    FormField(id="tone", label="基调和文风", type="text", default="natural"),
])


KNOWN_STEPS = {
    "story-init": FormStep(title="故事核心", fields=[
        FormField(id="themes", label="核心主题", type="textarea"),
        FormField(id="setting_era", label="时代背景", type="text"),
        FormField(id="ending", label="预定结局", type="textarea"),
        FormField(id="must_include", label="必须保留", type="textarea"),
        FormField(id="must_avoid", label="禁止出现", type="textarea"),
    ]),
    "character-management": FormStep(title="人物设定", fields=[
        FormField(id="protagonist.name", label="主角姓名", type="text"),
        FormField(id="protagonist.role", label="主角身份", type="text"),
        FormField(id="protagonist.personality", label="性格与缺陷", type="textarea"),
        FormField(id="protagonist.motivation", label="外在欲望与内在需求", type="textarea"),
        FormField(id="protagonist.voice", label="语言习惯与示例对白", type="textarea"),
        FormField(id="protagonist.arc", label="人物弧光终点", type="textarea"),
        FormField(id="key_characters", label="关键人物及关系", type="textarea"),
    ]),
    "worldbuilding": FormStep(title="世界观", fields=[
        FormField(id="world.overview", label="世界概况", type="textarea"),
        FormField(id="world.locations", label="重要地点", type="textarea"),
        FormField(id="world.systems", label="力量、科技或社会体系", type="textarea"),
        FormField(id="world.factions", label="势力与立场", type="textarea"),
        FormField(id="world.rules", label="不可违反的世界规则", type="textarea"),
    ]),
    "plot-structure": FormStep(title="剧情结构", fields=[
        FormField(id="plot.structure", label="结构模型", type="select", default="three-act",
                  options=["three-act", "five-act", "hero-journey", "save-the-cat", "kishotenketsu"]),
        FormField(id="plot.main_arc", label="主线推进", type="textarea"),
        FormField(id="plot.subplots", label="支线与人物线", type="textarea"),
        FormField(id="plot.foreshadowing", label="预设伏笔与回收", type="textarea"),
        FormField(id="plot.volume_plan", label="分卷计划", type="textarea"),
    ]),
}


class SkillFormCatalog:
    def __init__(self, gate: SkillGate, cache_root: Path,
                 generator: Callable[[Skill], dict] | None = None) -> None:
        self.gate = gate
        self.cache_root = cache_root
        self.generator = generator or self._fallback_form

    def build(self, mode: str, skill_names: list[str] | None = None) -> dict:
        available = self.gate.skills()
        if skill_names is None:
            names = [name for name in KNOWN_STEPS if name in available]
            names += [name for name, skill in available.items()
                      if name not in names and self._applies_to_creation(skill)]
        else:
            names = skill_names
        steps = [CORE_STEP.model_dump()]
        for name in names:
            skill = available.get(name)
            if not skill:
                continue
            form = self._form(skill)
            step = FormStep.model_validate({**form, "skill_name": name, "skill_hash": skill.content_hash})
            steps.append(step.model_dump())
        return {"version": 1, "mode": mode, "steps": steps}

    def _form(self, skill: Skill) -> dict:
        sidecar = skill.path / "forms" / "project.json"
        if sidecar.is_file():
            return json.loads(sidecar.read_text(encoding="utf-8"))
        if skill.name in KNOWN_STEPS:
            return KNOWN_STEPS[skill.name].model_dump(exclude={"skill_name", "skill_hash"})
        cache = self.cache_root / skill.name / f"{skill.content_hash}.json"
        if cache.is_file():
            return json.loads(cache.read_text(encoding="utf-8"))
        form = FormStep.model_validate(self.generator(skill)).model_dump(exclude={"skill_name", "skill_hash"})
        cache.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(cache, json.dumps(form, ensure_ascii=False, indent=2))
        return form

    @staticmethod
    def _fallback_form(skill: Skill) -> dict:
        labels = []
        for match in re.finditer(r"(?m)^\s*[-*]\s+(.+)$", skill.instructions):
            label = re.sub(r"[*`#]", "", match.group(1)).strip().split(" - ", 1)[0]
            if 3 <= len(label) <= 80 and not any(term in label.lower() for term in (".md", "frontmatter", "file", "directory", "story ")):
                labels.append(label.rstrip(":"))
            if len(labels) == 8:
                break
        if not labels:
            labels = ["需要该Skill遵守的具体要求"]
        fields = []
        safe_name = re.sub(r"[^a-zA-Z0-9_-]+", "-", skill.name).strip("-") or "skill"
        used = set()
        for index, label in enumerate(labels, 1):
            slug = re.sub(r"[^a-zA-Z0-9]+", "-", label.lower()).strip("-") or str(index)
            slug = slug[:40]
            while slug in used:
                slug += f"-{index}"
            used.add(slug)
            fields.append({"id": f"skill.{safe_name}.{slug}", "label": label, "type": "textarea"})
        return {"title": f"{skill.name}问题", "fields": fields}

    @staticmethod
    def _applies_to_creation(skill: Skill) -> bool:
        if skill.name in KNOWN_STEPS or (skill.path / "forms" / "project.json").is_file():
            return True
        header = skill.instructions[:1000].lower()
        return any(term in skill.name.lower() for term in ("init", "setup")) or any(
            term in header for term in ("start a new story", "initialize a story", "create a story", "new book")
        )


class WizardService:
    def __init__(self, db: Database, projects: ProjectStore, catalog: SkillFormCatalog) -> None:
        self.db = db
        self.projects = projects
        self.catalog = catalog

    def create(self, mode: str, skill_names: list[str] | None = None) -> dict:
        if mode not in {"short", "long"}:
            raise ValueError("Invalid project mode")
        wizard_id = uuid.uuid4().hex
        schema = self.catalog.build(mode, skill_names)
        answers = {}
        for step in schema["steps"]:
            for field in step["fields"]:
                if field.get("default") is not None:
                    answers[field["id"]] = {"value": field["default"], "policy": "suggestible"}
        self.db.save_wizard(wizard_id, "draft", mode, schema, answers)
        return self.get(wizard_id)

    def get(self, wizard_id: str) -> dict:
        wizard = self.db.get_wizard(wizard_id)
        if wizard is None:
            raise LookupError("Wizard not found")
        return wizard

    def list(self) -> list[dict]:
        return self.db.list_wizards()

    def delete(self, wizard_id: str) -> dict:
        with WIZARD_MUTATION_LOCK:
            wizard = self.get(wizard_id)
            if wizard.get("project_id") or wizard["status"] == "completed":
                raise ValueError("这份开书资料已经创建作品，不能从草稿列表删除。")
            if not self.db.delete_wizard(wizard_id):
                raise LookupError("Wizard not found")
            return {"id": wizard_id, "deleted": True}

    def save_answers(self, wizard_id: str, answers: dict) -> dict:
        with WIZARD_MUTATION_LOCK:
            wizard = self.get(wizard_id)
            if wizard["status"] == "completed":
                raise ValueError("Completed wizard cannot be modified")
            valid_ids = {field["id"] for step in wizard["schema"]["steps"] for field in step["fields"]}
            unknown = set(answers) - valid_ids
            if unknown:
                raise ValueError(f"Unknown wizard fields: {', '.join(sorted(unknown))}")
            merged = {**wizard["answers"], **answers}
            for key, answer in merged.items():
                if not isinstance(answer, dict) or answer.get("policy") not in {"locked", "suggestible", "generated"}:
                    raise ValueError(f"Invalid answer policy: {key}")
            self.db.save_wizard(wizard_id, wizard["status"], wizard["mode"], wizard["schema"], merged)
            return self.get(wizard_id)

    def analyze_gaps(self, wizard_id: str) -> dict:
        with WIZARD_MUTATION_LOCK:
            wizard = self.get(wizard_id)
            important = ["ending", "protagonist.arc"]
            if wizard["mode"] == "long":
                important += ["world.rules", "plot.main_arc"]
            fields = {field["id"]: field for step in wizard["schema"]["steps"] for field in step["fields"]}
            missing = [key for key in important if not wizard["answers"].get(key, {}).get("value") and key in fields]
            schema = wizard["schema"]
            schema["steps"] = [step for step in schema["steps"] if step.get("skill_name") != "runtime-followup"]
            if missing:
                followup = FormStep(
                    title="必要追问", skill_name="runtime-followup", skill_hash="deterministic",
                    fields=[FormField.model_validate({**fields[key], "required": True}) for key in missing],
                )
                schema["steps"].append(followup.model_dump())
                status = "gathering_input"
            else:
                status = "ready"
            self.db.save_wizard(wizard_id, status, wizard["mode"], schema, wizard["answers"])
            return self.get(wizard_id)

    def confirm(self, wizard_id: str) -> Project:
        with WIZARD_MUTATION_LOCK:
            wizard = self.get(wizard_id)
            if wizard.get("project_id"):
                return self.projects.get(wizard["project_id"])
            missing = []
            for step in wizard["schema"]["steps"]:
                for field in step["fields"]:
                    value = wizard["answers"].get(field["id"], {}).get("value")
                    if field.get("required") and (value is None or value == ""):
                        missing.append(field["id"])
            if missing:
                raise ValueError(f"Missing required answers: {', '.join(missing)}")
            values = {key: item.get("value") for key, item in wizard["answers"].items()}
            project = self.projects.create(ProjectCreate(
                title=str(values["title"]), mode=wizard["mode"], genre=str(values["genre"]),
                premise=str(values["premise"]), target_words=int(values["target_words"]),
                pov=str(values.get("pov") or "third-limited"), tone=str(values.get("tone") or "natural"),
                must_include=str(values.get("must_include") or ""), must_avoid=str(values.get("must_avoid") or ""),
            ))
            locked = []
            for key, item in wizard["answers"].items():
                if item.get("policy") == "locked":
                    self.db.save_lock(project.id, key, item.get("value"), f"wizard:{wizard_id}")
                    locked.append({"key": key, "value": item.get("value"), "source": f"wizard:{wizard_id}", "revision": 1})
            atomic_write(project.path / "continuity" / "locks.json",
                         json.dumps({"locks": locked}, ensure_ascii=False, indent=2))
            details = "\n\n## Confirmed Story Requirements\n\n" + "\n".join(
                f"- **{key}**: {value}" for key, value in values.items() if value not in (None, "")
            )
            atomic_write(
                project.path / "story.md",
                project.path.joinpath("story.md").read_text(encoding="utf-8") + details,
            )
            metadata = json.loads((project.path / "project.json").read_text(encoding="utf-8"))
            metadata["wizard_id"] = wizard_id
            metadata["story_requirements"] = values
            metadata["initialization_skills"] = [
                step["skill_name"] for step in wizard["schema"]["steps"]
                if step.get("skill_name") and step["skill_name"] != "runtime-followup"
            ]
            atomic_write(project.path / "project.json", json.dumps(metadata, ensure_ascii=False, indent=2))
            profile_id = values.get("platform_profile_id")
            if profile_id and profile_id != "none":
                project = self.projects.apply_platform_profile(project.id, str(profile_id))
            self.db.save_wizard(wizard_id, "completed", wizard["mode"], wizard["schema"],
                                wizard["answers"], project.id)
            return self.projects.get(project.id)
