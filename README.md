# Novel Flywheel Console

## 本地全文分析与增量终审

作品可以单独启用“正文全文分析与增量终审”。启用后，程序在草稿完成、初次润色、每轮返修和发布前对完整正文执行确定性规则扫描，并在全局 LTP 已启用时复用独立 CPU 进程和版本化缓存提取人物、事件与语义角色证据。

`review` 和 `reader_review` 仍读取标注抽样片段；`review` 额外接收有长度上限的全文本地摘要。首次 `final_review` 仍覆盖全部正文。首次终审未通过并发生返修时，系统复核改动窗口、相邻窗口及人物/事件关联窗口；修改超过正文 20%、影响超过 40% 的窗口，或涉及事件顺序、开头承诺、高潮、结尾、时间线、因果，或 LTP/窗口映射不可靠时，自动恢复全文终审。

原创候选只与本地项目稿件和导入参考资料比较，包括连续相似片段、人名近似、设定、关键情节和独特表达候选，不代表全网查重或法律结论。模型和 LTP 均不能直接覆盖正式稿；候选哈希、本地全文扫描和终审哈希一致后才允许发布。

Local multi-model writing workflow for short stories and long serial novels.

## Start

Run `start-novel-console.cmd`, then open `http://127.0.0.1:8765`.

## Model tools

Existing providers can be edited or deleted from **模型与 API**. Editing changes the visible name, protocol, and Base URL while preserving internal headers and timeout settings. A blank API Key keeps the current secret; entering a new key replaces it in the system credential store. Deleting a provider also deletes its model mappings. Primary role bindings using that provider are removed, while fallback references are cleared without removing the primary binding.

Each model mapping has a Tool Calling mode:

- `auto`: try native tool calling and fall back to an injected evidence package only when the provider explicitly rejects tools.
- `enabled`: require native tool calling and fail the stage if the provider rejects it.
- `disabled`: always use the injected evidence package.

Capability detection forces the provider to call a dedicated probe tool. OpenAI Chat and Anthropic requests both serialize the matching `tool_choice`. Thinking models that explicitly reject forced tool choice are retried once with normal tool selection. If a relay still ignores or strips the tool request, the result reports that no `probe_tool` call was returned instead of showing an unexplained failure.

Anthropic, OpenAI Chat, and OpenAI Responses adapters receive provider output as streams and aggregate it behind the existing response interface. The browser and workflow stages still receive complete responses; streaming keeps long generations active without requiring UI changes. Relays that reject optional stream parameters or streaming itself use compatibility fallbacks automatically.

Character material edits can retire removed settings and trigger a linked-material analysis through the configured `maintenance` role. The analysis only proposes exact, local patches to project materials such as plot arcs, timelines, promises, and constraints. It never changes manuscript prose. The user selects which proposals to apply; target hashes, project-relative paths, snapshots, and StoryState revisions prevent stale or partial updates.

Models can only use these project-scoped read tools:

- search prior chapters;
- read a bounded part of a numbered chapter;
- query canon and current character state;
- query foreshadowing, timeline, volume plans, and unresolved drift.

Models cannot pass file paths, write project files, or run commands. Each stage allows at most eight tool rounds. The deterministic flywheel remains the only writer of formal files and retains snapshots and rollback.

## Skills

Skills are scanned again for every stage. Global Skills are loaded from the configured roots, and project-specific Skills can be added under:

```text
<project>/.agents/skills/<skill-name>/SKILL.md
```

A project Skill with the same name overrides the global version on the next run; no server restart is required. A Skill is executable only when its instructions explicitly reference a bundled script, and executable Skills require approval for their current content hash. Unreferenced validation or development scripts are shown as auxiliary scripts and are never executed by the writing workflow.

The Skill page reports conservative conflicts with project rules, including fragmented-prose directives, named-author imitation, and direct formal-manuscript writes. These warnings are advisory and never silently disable or rewrite a Skill.

## StoryState and safe revision

Each novel has an independent versioned StoryState. Models read the same authoritative facts and submit candidate output; only Runtime can promote a candidate to the formal manuscript. Cancelled runs, failed quality checks, invalid polish output, and stale tasks cannot overwrite the last committed manuscript.

The workbench exposes StoryState sections for manual correction. A save creates a normal `manual_edit` candidate and a new revision; stale edits and edits during an active run are rejected. Automatic post-write StoryState updates continue without per-chapter confirmation.

The old workbench **范文笔感** uploader is retired in favor of the learning library. Existing `style-samples/profile.json` data migrates lazily to a versioned prose baseline when the project learning view is first read; old files remain intact for rollback. After migration, the managed legacy block is excluded from runtime style context to avoid injecting the same rules twice. The workbench now shows a read-only summary and links to **学习库** for changes.

Run details include a context summary built from existing events and receipts: model route, Skills, prompt and constraint size, token usage, execution mode, tool receipts, and fallback state. Secrets and raw request headers are not exposed.

Short-story polish uses bounded segments with adjacent boundaries, a compact story map, character state, locked facts, and stage-specific Skills. Claude primary polish starts with an 8,192 output limit because the configured relay repeatedly exhausted smaller limits before returning visible prose. Other polish routes retain dynamic limits, so ordinary segments do not inherit Claude's cost profile. Final structured review also uses 8,192 to avoid truncated JSON.

## Reference learning library

The top-level **学习库** stores reference prose locally and separately from story projects. It accepts pasted text, UTF-8 TXT, DOCX, text-extractable PDF, and public HTTP/HTTPS pages, deduplicates identical content by SHA-256, and preserves immutable source versions. URL import rejects local/private destinations at every redirect. Scanned-PDF OCR is intentionally not included.

References are organized by platform, content type, and an optional related project. Import recommends these values locally from the title, URL, and opening text; users can override them before or after import. Unknown material falls back to `reference_work`, while `competitor_work` is manual-only. Search and platform/type/project filters operate together without changing the globally reusable source.

Content type controls purpose rather than project voice: `reference_work` yields narrative mechanisms, `platform_rule` supplements only same-platform final review, `popular_sample` enables a no-model report for title/first three lines/opening 500 characters/middle/turns/ending, `writing_tutorial` yields methods, and only `competitor_work` enters originality comparison. No classification automatically changes prose style or adopts a mechanism.

Local mechanisms now require a located trigger excerpt, structural position, transfer guidance, incompatible conditions, and confidence. Low-confidence proposals must be confirmed before project adoption. Repetition remains a review-only finding; loop/recurrence anchors with nearby state-change signals are labeled as possible intentional repetition instead of receiving an unconditional deletion instruction.

**本地诊断** and **本地提炼** use deterministic Python rules only. **模型深度分析** uses the configured `reference_analysis` and `reference_synthesis` roles only after an explicit confirmation. Typed SQLite nodes, edges, evidence, and user revisions preserve provenance. Recommendations remain proposals until the user adopts them into one project.

Confirmed adoptions create versioned creative blueprints. Project learning also includes executable prose baselines, character voice profiles, epistemic boundaries, and scene briefs; active versions enter the existing planning/drafting/review/polish context, while stale versions are excluded. Character or world edits mark derived artifacts for review without rewriting an outline or manuscript.

**项目资料** and **学习库** render those same active or stale learning artifacts as readable Chinese sections, including versions and review status; they do not create another copy. Editing remains centralized in **学习库**. The new-book wizard lists every imported reference as a creation starting point. If a selected reference has not been locally distilled yet, the wizard performs that deterministic step first, then copies only the transferable mechanisms into editable premise and plot fields. The original “自己构思” path remains unchanged.

Candidate outlines use the existing planning route and are stored below `<project>/learning/candidates/`. Targeted `line_edit` uses its own role and stores candidate JSON below `<project>/learning/line-edits/`. Neither path overwrites formal files. Optional LTP neural NLP is installed, enabled, disabled, or uninstalled explicitly from **模型与 API**; it runs in a separate CPU process and fails open to deterministic rules.

Structural correction is scene-targeted. Every scene has a stable `scene-NN` id; a valid correction plan must include deterministic checks and may target at most 40% of scenes. Invalid or truncated plans stop the correction pass and preserve `best-candidate.md` instead of rewriting the whole manuscript. Exact consecutive duplicate paragraph blocks are removed locally before review.

Revision planning uses compact Skill/constraint prompts. If the planning role returns empty, truncated, or invalid JSON, the Runtime retries the plan once with the review role; a second invalid result fails closed and preserves the best candidate.

Polish input has circuit breakers: 120,000 tokens for the initial pass, 60,000 for each structural correction pass, and 220,000 across the run. Checkpoints are reused when resuming the same pass; failed editorial rounds are never reused as accepted corrections.

Ordinary prose polish uses bounded chunks and merges tiny trailing chunks when the merged request remains safe. Structural correction sends each targeted story scene once instead of repeating a scene-level task across subchunks. Its explicit length contract is 60%-180% of the source scene; ordinary polish remains 70%-160%. All instructions precede the manuscript marker so the model sees only source prose after `MANUSCRIPT SEGMENT`.

Only locally accepted candidates create checkpoints; rejected candidates remain retryable on resume.

For structural correction only, candidates in the 50%-60% compression gray zone may continue to final review when locked facts and local checks still pass. Runtime also re-aligns forbidden-text repair tasks to the scene that actually contains the exact text.

Operational details, log meanings, recovery behavior, and documentation requirements are in [`docs/maintenance.md`](docs/maintenance.md).

## Long novels

Long setup may produce `memory/volumes.json` with machine-readable boundaries. When a generated chapter reaches `end_chapter`, the flywheel runs a volume audit and writes `memory/audits/volume-NN.json`.

A failed audit keeps the completed volume-ending chapter but blocks entry into the next volume. Resolve the audit findings and mark the audit passed before continuing.

Relevant chapter retrieval uses SQLite FTS and returns bounded matching prose excerpts rather than loading the whole novel into model context.

## Skill-driven project wizard

New projects use a resumable wizard. The wizard combines a stable core form with questions from `story-init`, `character-management`, `worldbuilding`, `plot-structure`, and compatible project-form sidecars under `forms/project.json`.

Unknown initialization Skills receive a validated generated form cached by Skill content hash under `data/skill-forms`. Updating a Skill selects a new cache entry automatically. Every answer is stored as one of:

- `locked`: program-enforced and included in every later model stage;
- `suggestible`: models may recommend changes;
- `generated`: the planning model may supply the value.

Before confirmation, **检查关键缺口** adds required follow-ups for missing endings, character arcs, world rules, and long-form main arcs. Confirmation creates the Story Skills schema-v2 project layout and saves locks in SQLite and `continuity/locks.json`.

## Controlled Skill Runtime

After project creation, the console runs the selected initialization Skills through a controlled runtime. External models may read story files, list entities, request missing input, and submit file or registry proposals. They cannot write directly.

Each Skill has a path allowlist. Proposed Markdown requires YAML frontmatter, locked facts are checked before acceptance, and conflicts create change requests. Accepted proposals are applied as one snapshot-protected transaction followed by Story CLI `reindex`, `links`, and `validate`.

The runtime exposes no general shell, arbitrary path, browser, MCP, or Codex tool access. Write-capable Skill execution requires native Tool Calling; prompt fallback is rejected rather than treated as successful execution.

## Existing project migration

The workbench can preview and run migration for an older project. Migration preserves legacy files, maps the old outline and canon into the canonical structure, sends ambiguous facts to `migration-report.json`, rebuilds registries, and restores the snapshot if Story CLI validation fails.
