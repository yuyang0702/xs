import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from novel_flywheel.domain.models import ToolDefinition
from novel_flywheel.memory import StoryMemory
from novel_flywheel.projects import Project


class _StrictArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _SearchArgs(_StrictArgs):
    query: str = Field(min_length=1)
    limit: int = Field(default=6, ge=1, le=10)


class _ReadArgs(_StrictArgs):
    chapter_number: int = Field(ge=1)
    start: int = Field(default=0, ge=0)
    length: int = Field(default=4000, ge=1, le=8000)


class _QueryArgs(_StrictArgs):
    query: str = ""


class StoryToolbox:
    def __init__(self, project: Project, memory: StoryMemory) -> None:
        self.project = project
        self.memory = memory

    def definitions(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(name="search_chapters", description="Search prior chapters and return bounded excerpts", input_schema=_SearchArgs.model_json_schema()),
            ToolDefinition(name="read_chapter", description="Read a bounded range from one chapter", input_schema=_ReadArgs.model_json_schema()),
            ToolDefinition(name="get_canon", description="Read confirmed story canon", input_schema=_QueryArgs.model_json_schema()),
            ToolDefinition(name="get_character_state", description="Read the latest character state", input_schema=_QueryArgs.model_json_schema()),
            ToolDefinition(name="get_foreshadowing", description="Read foreshadowing records", input_schema=_QueryArgs.model_json_schema()),
            ToolDefinition(name="get_timeline", description="Read timeline records", input_schema=_QueryArgs.model_json_schema()),
            ToolDefinition(name="get_volume_plan", description="Read volume plans", input_schema=_QueryArgs.model_json_schema()),
            ToolDefinition(name="get_drift_findings", description="Read unresolved continuity drift", input_schema=_QueryArgs.model_json_schema()),
        ]

    def execute(self, name: str, arguments: dict) -> dict:
        handlers = {
            "search_chapters": self._search,
            "read_chapter": self._read,
            "get_canon": lambda args: {"items": self.memory.context(self.project.id, args.query)["canon"]},
            "get_character_state": lambda args: {"state": self.memory.context(self.project.id, args.query)["recent_state"]},
            "get_drift_findings": lambda args: {"items": self.memory.context(self.project.id, args.query)["drift"]},
            "get_foreshadowing": lambda args: self._json_file("memory/foreshadowing.json"),
            "get_timeline": lambda args: self._json_file("memory/timeline.json"),
            "get_volume_plan": lambda args: self._json_file("memory/volumes.json"),
        }
        if name not in handlers:
            raise ValueError(f"Unknown tool: {name}")
        model = _SearchArgs if name == "search_chapters" else _ReadArgs if name == "read_chapter" else _QueryArgs
        return handlers[name](model.model_validate(arguments))

    def _search(self, args: _SearchArgs) -> dict:
        items = self.memory.search_chapters(self.project.id, args.query, args.limit)
        for item in items:
            item["excerpt"] = item.get("excerpt", "")[:1200]
        return {"items": items}

    def _read(self, args: _ReadArgs) -> dict:
        path = self.project.path / "chapters" / f"chapter-{args.chapter_number:02d}.md"
        if not path.is_file():
            raise FileNotFoundError(f"Chapter not found: {args.chapter_number}")
        text = path.read_text(encoding="utf-8")
        return {"chapter_number": args.chapter_number, "start": args.start, "text": text[args.start:args.start + args.length]}

    def _json_file(self, relative: str) -> dict:
        path = self.project.path / Path(relative)
        if not path.is_file():
            return {"items": []}
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {"items": value}
