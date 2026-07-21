# Read-only Agent Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give each external model a bounded set of read-only story tools, automatic prompt fallback, project-local Skill discovery, relevant prose retrieval, and automatic volume-boundary audits.

**Architecture:** Extend the existing provider-neutral request/response models with normalized tool definitions and calls. `ModelGateway` owns the bounded agent loop and invokes a project-scoped `StoryToolbox`; workflows remain deterministic and retain exclusive authority over formal writes. SQLite stores execution receipts and volume audit state, while unsupported providers retry once with a prebuilt evidence package.

**Tech Stack:** Python 3.11, Pydantic 2, FastAPI, httpx, SQLite FTS5, pytest, vanilla JavaScript/CSS, existing CrewAI Flow wrapper.

---

## File Map

- Create `src/novel_flywheel/tools.py`: read-only tool definitions, argument validation, project-scoped execution, and result bounds.
- Modify `src/novel_flywheel/domain/models.py`: normalized tool definition, tool call, request, and response fields.
- Modify `src/novel_flywheel/providers/openai_chat.py`: OpenAI Chat tool serialization and call parsing.
- Modify `src/novel_flywheel/providers/openai_responses.py`: Responses API tool serialization and call parsing.
- Modify `src/novel_flywheel/providers/anthropic.py`: Anthropic tool serialization and call parsing.
- Modify `src/novel_flywheel/providers/http.py`: typed capability-rejection error.
- Modify `src/novel_flywheel/models.py`: bounded tool loop, capability mode, fallback retry, and receipts.
- Modify `src/novel_flywheel/memory.py`: relevant prose snippets and structured memory queries.
- Modify `src/novel_flywheel/skills.py`: dynamic project Skill root and precedence.
- Modify `src/novel_flywheel/db.py`: tool receipts, volume plans, and audit persistence.
- Modify `src/novel_flywheel/workflows.py`: stage tool wiring, evidence fallback, volume plans, and audit gate.
- Modify `src/novel_flywheel/api/providers.py`: model tool-support configuration.
- Modify `src/novel_flywheel/api/runs.py`: detailed execution and audit status.
- Modify `src/novel_flywheel/static/index.html`: tool-support selector and run detail surface.
- Modify `src/novel_flywheel/static/app.js`: send/render capability and run receipt data.
- Modify `src/novel_flywheel/static/app.css`: compact execution badges and audit rows.
- Add focused tests under `tests/` and `tests/providers/` for each behavior.

### Task 1: Normalize Provider Tool Calls

**Files:**
- Modify: `src/novel_flywheel/domain/models.py`
- Modify: `src/novel_flywheel/providers/openai_chat.py`
- Modify: `src/novel_flywheel/providers/openai_responses.py`
- Modify: `src/novel_flywheel/providers/anthropic.py`
- Test: `tests/providers/test_tools.py`

- [ ] **Step 1: Write failing adapter tests**

Create tests that submit this common request and assert normalized calls:

```python
request = ModelRequest(
    model="writer",
    messages=[Message(role="user", content="Find the key")],
    tools=[ToolDefinition(
        name="search_chapters",
        description="Search chapters",
        input_schema={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    )],
)
assert response.tool_calls == [ToolCall(id="call-1", name="search_chapters", arguments={"query": "key"})]
```

Cover OpenAI Chat `message.tool_calls`, Responses `output[type=function_call]`, and Anthropic `content[type=tool_use]`. Assert each outgoing payload uses its provider-native schema.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/providers/test_tools.py -v`

Expected: collection or assertion failure because `ToolDefinition`, `ToolCall`, and adapter serialization do not exist.

- [ ] **Step 3: Add the minimal common types and adapter mappings**

Add these shapes to `domain/models.py` and preserve existing text behavior:

```python
class ToolDefinition(BaseModel):
    name: str
    description: str
    input_schema: dict

class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict

class ModelRequest(BaseModel):
    model: str
    messages: list[Message]
    temperature: float | None = None
    max_output_tokens: int | None = None
    response_schema: dict | None = None
    tools: list[ToolDefinition] = []

class ModelResponse(BaseModel):
    text: str = ""
    tool_calls: list[ToolCall] = []
    finish_reason: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    raw_request_id: str | None = None
    provider_state: dict = {}
```

Serialize and parse only the documented fields exercised by the fixtures. Store the provider assistant block needed for the next turn in `provider_state`.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/providers/test_tools.py tests/providers/test_protocols.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/novel_flywheel/domain/models.py src/novel_flywheel/providers tests/providers/test_tools.py
git commit -m "feat: normalize provider tool calls"
```

### Task 2: Add Project-scoped Read-only Tools

**Files:**
- Create: `src/novel_flywheel/tools.py`
- Modify: `src/novel_flywheel/memory.py`
- Test: `tests/test_tools.py`
- Modify: `tests/test_memory.py`

- [ ] **Step 1: Write failing toolbox and snippet tests**

Test that `search_chapters` returns a bounded excerpt containing the match, `read_chapter` accepts only a chapter number and bounded offsets, and unknown tools/arguments fail:

```python
toolbox = StoryToolbox(project, memory)
result = toolbox.execute("search_chapters", {"query": "brass key", "limit": 2})
assert "brass key" in result["items"][0]["excerpt"].lower()
assert len(result["items"][0]["excerpt"]) <= 1200
with pytest.raises(ValueError, match="Unknown tool"):
    toolbox.execute("read_file", {"path": "../secret"})
```

Also cover canon, recent character state, foreshadowing, timeline, volume plan, drift findings, missing optional files, maximum `limit`, and maximum chapter read length.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_tools.py tests/test_memory.py -v`

Expected: FAIL because `StoryToolbox` and excerpts do not exist.

- [ ] **Step 3: Implement bounded retrieval and dispatch**

Add `StoryMemory.search_chapters()` selecting FTS `snippet(chapter_search, 3, '', '', ' ... ', 32)` and return `excerpt` with each hit. Implement `StoryToolbox.definitions()` and an explicit dispatch map:

```python
HANDLERS = {
    "search_chapters": self._search_chapters,
    "read_chapter": self._read_chapter,
    "get_canon": self._get_canon,
    "get_character_state": self._get_character_state,
    "get_foreshadowing": self._get_foreshadowing,
    "get_timeline": self._get_timeline,
    "get_volume_plan": self._get_volume_plan,
    "get_drift_findings": self._get_drift_findings,
}
```

Parse arguments with small Pydantic models. Derive chapter paths as `project.path / "chapters" / f"chapter-{number:02d}.md"`; never accept a path. Cap search at 10 results, excerpts at 1,200 characters, and direct reads at 8,000 characters.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/test_tools.py tests/test_memory.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/novel_flywheel/tools.py src/novel_flywheel/memory.py tests/test_tools.py tests/test_memory.py
git commit -m "feat: add read-only story tools"
```

### Task 3: Implement the Bounded Agent Loop and Fallback

**Files:**
- Modify: `src/novel_flywheel/providers/http.py`
- Modify: `src/novel_flywheel/models.py`
- Modify: `src/novel_flywheel/db.py`
- Test: `tests/test_models.py`
- Modify: `tests/test_db.py`

- [ ] **Step 1: Write failing loop, fallback, and receipt tests**

Use a fake adapter that first returns a tool call and then final text. Assert the executor result is sent back, only eight rounds are allowed, and receipts contain `native_tools`. Use a second fake that raises `ToolCapabilityError` and assert one retry without tools plus `degraded_prompt_mode`. Assert a 401-like ordinary provider error is propagated.

```python
result = await gateway.complete_with_tools(
    "review", system, user, toolbox,
    fallback_context=lambda: "EVIDENCE PACKAGE",
)
assert result.text == "approved"
assert result.receipt["execution_mode"] == "native_tools"
assert result.receipt["tool_call_count"] == 1
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_models.py tests/test_db.py -v`

Expected: FAIL because the agent method and receipt table do not exist.

- [ ] **Step 3: Add capability error, migration, and loop**

Add `ToolCapabilityError` only for provider responses that explicitly reject tool parameters. Add `tool_receipts` with `run_id`, `stage`, `model_id`, `execution_mode`, `tool_name`, sanitized `arguments_json`, `result_size`, `duration_ms`, `status`, and `created_at`.

Implement `complete_with_tools` as a loop over `adapter.complete()`. Validate and execute calls through `StoryToolbox`, append normalized tool-result messages, accumulate usage, and stop at eight rounds. For model capability `tools=disabled`, skip the native attempt. For `auto`, catch only `ToolCapabilityError`, rebuild a plain request containing the fallback evidence, and retry once.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/test_models.py tests/test_db.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/novel_flywheel/providers/http.py src/novel_flywheel/models.py src/novel_flywheel/db.py tests/test_models.py tests/test_db.py
git commit -m "feat: run bounded model tool loops"
```

### Task 4: Discover Project-local Skills Dynamically

**Files:**
- Modify: `src/novel_flywheel/skills.py`
- Modify: `src/novel_flywheel/workflows.py`
- Test: `tests/test_skills.py`
- Modify: `tests/test_workflows.py`

- [ ] **Step 1: Write failing precedence and no-restart tests**

Create a global and project Skill with the same name. Assert `skills(project.path)` selects the project copy. Add a new Skill after `SkillGate` construction and assert the next call discovers it.

```python
gate = SkillGate(db, SkillScanner([global_root]))
write_skill(project.path / ".agents" / "skills", "dialogue", "Project voice")
assert "Project voice" in gate.run_required(
    "draft", ["dialogue"], project_root=project.path,
).prompt
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_skills.py -v`

Expected: FAIL because project roots are not accepted.

- [ ] **Step 3: Implement per-call roots and precedence**

Make `SkillScanner.scan(extra_roots=[])` scan global roots first and project root last so the last definition wins. Add `project_root` to `SkillGate.skills()` and `run_required()`. Pass `project.path` from every workflow stage and archive call.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/test_skills.py tests/test_workflows.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/novel_flywheel/skills.py src/novel_flywheel/workflows.py tests/test_skills.py tests/test_workflows.py
git commit -m "feat: load project-local skills per run"
```

### Task 5: Wire Tools and Evidence into Every Workflow Stage

**Files:**
- Modify: `src/novel_flywheel/workflows.py`
- Modify: `src/novel_flywheel/prompts.py`
- Test: `tests/test_workflows.py`

- [ ] **Step 1: Write failing stage integration tests**

Assert long planning, draft, review, polish, final review, and maintenance calls receive a `StoryToolbox`. Assert short-story polishing still receives the complete current manuscript. Assert fallback evidence contains relevant excerpts and does not contain an unrelated full chapter.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_workflows.py -v`

Expected: FAIL because `_stage` still calls text-only `complete`.

- [ ] **Step 3: Route stages through the agent gateway**

Construct one `StoryToolbox(project, self.memory)` per pipeline. Change `_stage` to call `complete_with_tools` and supply a stage-specific fallback builder. Keep current manuscript content in the user message; tools provide historical evidence only. Add explicit system language that tools are read-only evidence sources and that absent data must not be invented.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/test_workflows.py tests/test_models.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/novel_flywheel/workflows.py src/novel_flywheel/prompts.py tests/test_workflows.py
git commit -m "feat: give workflow roles story tools"
```

### Task 6: Persist Volume Plans and Enforce Volume Audits

**Files:**
- Modify: `src/novel_flywheel/db.py`
- Modify: `src/novel_flywheel/workflows.py`
- Modify: `src/novel_flywheel/prompts.py`
- Test: `tests/test_workflows.py`
- Modify: `tests/test_db.py`

- [ ] **Step 1: Write failing volume boundary tests**

Test machine-readable setup output with volumes ending at chapters 12 and 25. Completing chapter 12 must invoke one `volume_audit`; completing chapter 11 must invoke none. A score below 80 persists a blocked audit and prevents chapter 13, while leaving chapter 12 committed.

```python
assert db.get_volume_audit(project.id, 1)["status"] == "blocked"
assert (project.path / "chapters" / "chapter-12.md").is_file()
with pytest.raises(RuntimeError, match="volume audit"):
    await service.run_chapter(project.id, "Start volume two", use_crewai=False)
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_workflows.py tests/test_db.py -v`

Expected: FAIL because volume tables and workflow gates do not exist.

- [ ] **Step 3: Add volume persistence and audit workflow**

Require long setup maintenance JSON to contain:

```json
{"facts": [], "volumes": [{"number": 1, "start_chapter": 1, "end_chapter": 12, "goal": "...", "completion_conditions": ["..."]}]}
```

Persist it to `memory/volumes.json` and SQLite. Before a chapter run, reject entry into a volume following a blocked audit. After a boundary chapter is committed and indexed, build bounded chapter batches, call `volume_audit`, write `memory/audits/volume-01.json`, record drift issues, and store `passed` or `blocked`. Add `volume_audit` to role bindings and map it to `revision-continuity`.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/test_workflows.py tests/test_db.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/novel_flywheel/db.py src/novel_flywheel/workflows.py src/novel_flywheel/prompts.py tests/test_workflows.py tests/test_db.py
git commit -m "feat: audit long novels at volume boundaries"
```

### Task 7: Expose Capability and Execution Status in the Console

**Files:**
- Modify: `src/novel_flywheel/api/providers.py`
- Modify: `src/novel_flywheel/api/runs.py`
- Modify: `src/novel_flywheel/static/index.html`
- Modify: `src/novel_flywheel/static/app.js`
- Modify: `src/novel_flywheel/static/app.css`
- Test: `tests/api/test_providers.py`
- Modify: `tests/api/test_runs.py`
- Modify: `tests/test_console.py`

- [ ] **Step 1: Write failing API and console tests**

Assert model creation accepts `tool_support` only as `auto`, `enabled`, or `disabled`; default is `auto`. Assert run detail returns execution modes, tool-call counts, fallback reasons, and volume audit status. Assert the HTML contains the capability selector and execution detail target.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/api/test_providers.py tests/api/test_runs.py tests/test_console.py -v`

Expected: FAIL because the API and controls do not expose these fields.

- [ ] **Step 3: Implement the compact status UI**

Extend `ModelCreate`:

```python
class ModelCreate(BaseModel):
    display_name: str = Field(min_length=1)
    model_name: str = Field(min_length=1)
    tool_support: Literal["auto", "enabled", "disabled"] = "auto"
```

Store it inside `capabilities_json`. Return grouped receipt data from `GET /api/runs/{run_id}`. Add a three-option selector to model setup and render `原生工具`, `提示降级`, tool count, fallback reason, and volume audit status in run details. Keep controls compact and use existing panel styles.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/api/test_providers.py tests/api/test_runs.py tests/test_console.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/novel_flywheel/api src/novel_flywheel/static tests/api tests/test_console.py
git commit -m "feat: show model tool execution status"
```

### Task 8: End-to-end Verification and Documentation

**Files:**
- Create: `README.md`
- Modify: `docs/superpowers/specs/2026-07-22-readonly-agent-tools-design.md` only if implementation establishes a narrower documented limit.

- [ ] **Step 1: Document configuration and safety boundaries**

Document local startup, provider `tool_support`, fallback meaning, project Skill path, read-only tool list, eight-round limit, volume audit blocking behavior, and the fact that only the flywheel writes formal files.

- [ ] **Step 2: Run the full automated suite**

Run: `pytest -q`

Expected: all tests pass with no new warnings.

- [ ] **Step 3: Start the local server and exercise health/API paths**

Run: `python -m novel_flywheel.launcher`

Expected: server starts locally; `/api/health` returns `{"status":"ok"}`; provider and run-detail endpoints return the new fields.

- [ ] **Step 4: Verify the console at desktop and mobile widths**

Use Playwright against the local URL at 1440x900 and 390x844. Verify no overlap, clipped text, horizontal page overflow, or broken provider/run controls. Capture screenshots as test evidence, not repository assets.

- [ ] **Step 5: Inspect final repository state**

Run: `git diff --check` and `git status --short`

Expected: no whitespace errors; only intended implementation and documentation changes remain.

- [ ] **Step 6: Commit documentation**

```powershell
git add README.md docs/superpowers/specs/2026-07-22-readonly-agent-tools-design.md
git commit -m "docs: explain model tools and volume audits"
```

